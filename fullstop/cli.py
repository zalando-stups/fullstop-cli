import datetime
import json
import re
import time

import click
import fullstop
import stups_cli.config
import yaml
import zign.api
from clickclick import Action, AliasedGroup, OutputFormat, UrlType, print_table
from fullstop.api import request, session
from fullstop.time import normalize_time

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

output_option = click.option('-o', '--output', type=click.Choice(['text', 'json', 'tsv']), default='text',
                             help='Use alternative output format')


def parse_time(s: str) -> float:
    '''
    >>> parse_time('2015-04-14T19:09:01.000Z') > 0
    True
    '''
    try:
        utc = datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ')
        ts = time.time()
        utc_offset = datetime.datetime.fromtimestamp(ts) - datetime.datetime.utcfromtimestamp(ts)
        local = utc + utc_offset
        return local.timestamp()
    except Exception as e:
        print(e)
        return None


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo('Fullstop CLI {}'.format(fullstop.__version__))
    ctx.exit()


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.option('-V', '--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True,
              help='Print the current version number and exit.')
@click.pass_context
def cli(ctx):
    ctx.obj = stups_cli.config.load_config('fullstop')


def get_token():
    try:
        token = zign.api.get_token('fullstop', ['uid'])
    except Exception as e:
        raise click.UsageError(str(e))
    return token


def parse_since(s):
    return normalize_time(s, past=True).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


@cli.command('configure')
@click.pass_obj
def configure(config):
    '''Configure fullstop. CLI'''
    url = click.prompt('Fullstop URL', default=config.get('url'), type=UrlType())
    accounts = click.prompt('AWS account IDs (comma separated)', default=config.get('accounts'))

    config = {'url': url, 'accounts': accounts}

    with Action('Storing configuration..'):
        stups_cli.config.store_config(config, 'fullstop')


@cli.command('types')
@output_option
@click.pass_obj
def types(config, output):
    '''List violation types'''
    url = config.get('url')
    if not url:
        raise click.ClickException('Missing configuration URL. Please run "stups configure".')

    token = get_token()

    r = request(url, '/api/violation-types', token)
    r.raise_for_status()
    data = r.json()

    rows = []
    for row in data:
        row['created_time'] = parse_time(row['created'])
        rows.append(row)

    rows.sort(key=lambda r: r['id'])

    with OutputFormat(output):
        print_table(['id', 'violation_severity', 'created_time', 'help_text'],
                    rows, titles={'created_time': 'Created', 'violation_severity': 'Sev.'})


def meta_matches(meta_info, meta_filter: str):
    '''
    >>> meta_matches(None, None)
    True
    >>> meta_matches(None, '1: 2')
    False
    >>> meta_matches('{"1": "2"}', '1= 2')
    True
    '''
    if not isinstance(meta_info, dict):
        try:
            meta_info = json.loads(meta_info)
        except:
            meta_info = None

    try:
        res = {}
        for key_val in meta_filter.split(','):
            key, sep, val = key_val.partition('=')
            res[key.strip()] = val.strip()
        meta_filter = res
    except:
        meta_filter = {}

    if not meta_filter:
        return True
    if not meta_info:
        return False

    if not isinstance(meta_info, dict):
        return False
    if not isinstance(meta_filter, dict):
        return False

    for key, val in meta_filter.items():
        if str(meta_info.get(key)) != val:
            return False
    return True


def meta_matches_re(meta_info: str, regular_exp: str):
    '''
    >>> meta_matches_re(None, None)
    False
    >>> meta_matches_re(None, 'abc')
    False
    >>> meta_matches_re({}, 'abc')
    False
    >>> meta_matches_re('{"1": "2"}', '^\{.*\}')
    True
    >>> meta_matches_re('{"app_name": "foobar"}', '.*app_name\\"\: \\"foobar.*')
    True
    >>> meta_matches_re('{"app_name": "foobar"}', 'nomatch')
    False
    >>> meta_matches_re('app_name, foobar', 'app_name')
    True
    '''
    if not meta_info:
        return False

    if not isinstance(meta_info, str):
        return False

    if not regular_exp:
        return True

    return re.match(regular_exp, meta_info) is not None


def format_meta_info(meta_info):
    '''
    >>> format_meta_info(None)
    ''
    >>> format_meta_info({1: 2})
    '1: 2'
    >>> format_meta_info('foo')
    'foo'
    '''
    if not meta_info:
        return ''
    if isinstance(meta_info, str):
        return meta_info
    # remove application properties from meta_info, as they are now separate columns in the output table
    meta_info.pop('application_id', None)
    meta_info.pop('application_version', None)
    return yaml.safe_dump(meta_info).strip('{} \n').replace('\n', ', ')


accounts_option = click.option('--accounts', metavar='ACCOUNT_IDS',
                               help='AWS account IDs to filter for (default: your configured accounts)')
since_option = click.option('-s', '--since', default='1d', metavar='TIME_SPEC',
                            help='Only show violations newer than TIME_SPEC (24h, 30d, ..)')
type_option = click.option('-t', '--type', metavar='VIOLATION_TYPE', help='Only show violations of given type')
severity_option = click.option('--severity')
region_option = click.option('-r', '--region', metavar='AWS_REGION_ID', help='Filter by region')
application_ids_option = click.option('--applications', metavar='APPLICATIONS', help='Filter by application ids')
application_version_ids_option = click.option('--application-versions', metavar='APPLICATION_VERSIONS',
                                              help='Filter by application version ids')
meta_option = click.option('-m', '--meta', metavar='KEY=VAL', help='Filter by meta info (k1=v1,k2=v2,..)')
remeta_option = click.option('-x', '--remeta', metavar='REGEX', help='Filter by meta info by regular expression')
limit_option = click.option('-l', '--limit', metavar='N', help='Limit number of results', type=int, default=20)


@cli.command('list-violations')
@output_option
@accounts_option
@since_option
@type_option
@severity_option
@region_option
@application_ids_option
@application_version_ids_option
@meta_option
@remeta_option
@limit_option
@click.option('--all', is_flag=True, help='Show resolved violations too')
@click.pass_obj
def list_violations(config, output, since, region, meta, remeta, limit, all, **kwargs):
    '''List violations'''
    url = config.get('url')
    if not url:
        raise click.ClickException('Missing configuration URL. Please run "stups configure".')

    kwargs['accounts'] = kwargs.get('accounts') or config.get('accounts')

    token = get_token()

    params = {'size': limit, 'sort': 'id,DESC'}
    params['from'] = parse_since(since)
    params['application-ids'] = kwargs.get('applications')
    params['application-version-ids'] = kwargs.get('application_versions')
    params.update(kwargs)

    r = request(url, '/api/violations', token, params=params)
    r.raise_for_status()
    data = r.json()['content']

    if (all):
        params['checked'] = 'true'
        r = request(url, '/api/violations', token, params=params)
        r.raise_for_status()
        data.extend(r.json()['content'])

    rows = []
    for row in data:
        if region and row['region'] != region:
            continue
        if meta and not meta_matches(row['meta_info'], meta):
            continue
        if remeta and not meta_matches_re(format_meta_info(row['meta_info']), remeta):
            continue
        row['violation_type'] = row['violation_type']['id']
        row['created_time'] = parse_time(row['created'])
        row['meta_info'] = format_meta_info(row['meta_info'])
        rows.append(row)

    # we get the newest violations first, but we want to print them in order
    rows.reverse()

    with OutputFormat(output):
        print_table(['account_id',
                     'region',
                     'id',
                     'violation_type',
                     'instance_id',
                     'application_id',
                     'application_version_id',
                     'meta_info',
                     'comment',
                     'created_time'],
                    rows, titles={'created_time': 'Created',
                                  'application_id': 'Application',
                                  'application_version_id': 'Application Version'})


@cli.command('resolve-violations')
@accounts_option
@since_option
@click.option('-i', '--violation-ids', metavar='VIOLATION_IDS', help='Resolve specific violations, ' +
                                                                     'multiple ID\'s comma separated')
@severity_option
@type_option
@region_option
@application_ids_option
@application_version_ids_option
@meta_option
@remeta_option
@limit_option
@click.argument('comment')
@click.pass_obj
def resolve_violations(config, comment, since, region, meta, remeta, limit, violation_ids, **kwargs):
    '''Resolve violations'''
    url = config.get('url')
    if not url:
        raise click.ClickException('Missing configuration URL. Please run "stups configure".')

    kwargs['accounts'] = kwargs.get('accounts') or config.get('accounts')

    if all([not violation_ids, not kwargs['accounts'], not kwargs['type'], not region]):
        raise click.UsageError('At least one of --accounts, --type, --region or --violation-ids must be specified')

    token = get_token()

    params = {'size': limit, 'sort': 'id,DESC'}
    params['from'] = parse_since(since)
    params['application-ids'] = kwargs.get('applications')
    params['application-version-ids'] = kwargs.get('application_versions')
    params.update(kwargs)
    data = {}
    if violation_ids:
        data['content'] = []
        for violation_id in violation_ids.split(','):
            r = request(url, '/api/violations/{}'.format(violation_id), token, params=params)
            r.raise_for_status()
            data['content'].append(r.json())
    else:
        r = request(url, '/api/violations', token, params=params)
        r.raise_for_status()
        data = r.json()

    for row in data['content']:
        if region and row['region'] != region:
            continue
        if meta and not meta_matches(row['meta_info'], meta):
            continue
        if remeta and not meta_matches_re(format_meta_info(row['meta_info']), remeta):
            continue
        if row['comment']:
            # already resolved, skip
            continue
        try:
            with Action('Resolving violation {}/{} {} {}..'.format(row['account_id'], row['region'],
                                                                   row['violation_type']['id'], row['id'])):
                r = session.post(url + '/api/violations/{}/resolution'.format(row['id']), data=comment,
                                 headers={'Authorization': 'Bearer {}'.format(token)})
                r.raise_for_status()
        except:
            # continue, error was printed by Action already
            pass


def main():
    cli()
