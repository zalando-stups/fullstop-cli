import datetime

import click

import time
import zign.api
from clickclick import AliasedGroup, print_table, OutputFormat, Action, UrlType

import fullstop
import stups_cli.config
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


@cli.command('list-violations')
@output_option
@click.option('--accounts', metavar='ACCOUNT_IDS',
              help='AWS account IDs to filter for (default: your configured accounts)')
@click.option('-s', '--since', default='1d', metavar='TIME_SPEC', help='Only show violations newer than')
@click.option('--severity')
@click.option('-t', '--type', metavar='VIOLATION_TYPE', help='Only show violations of given type')
@click.option('-r', '--region', metavar='AWS_REGION_ID', help='Filter by region')
@click.option('-l', '--limit', metavar='N', help='Limit number of results', type=int, default=20)
@click.option('--all', is_flag=True, help='Show resolved violations too')
@click.pass_obj
def list_violations(config, output, since, region, limit, all, **kwargs):
    '''List violations'''
    url = config.get('url')
    if not url:
        raise click.ClickException('Missing configuration URL. Please run "stups configure".')

    kwargs['accounts'] = kwargs.get('accounts') or config.get('accounts')

    token = get_token()

    params = {'size': limit, 'sort': 'id,DESC'}
    params['since'] = parse_since(since)
    params.update(kwargs)
    r = request(url, '/api/violations', token, params=params)
    r.raise_for_status()
    data = r.json()

    rows = []
    for row in data['content']:
        if region and row['region'] != region:
            continue
        if row['comment'] and not all:
            continue
        row['violation_type'] = row['violation_type']['id']
        row['created_time'] = parse_time(row['created'])
        row['meta_info'] = (row['meta_info'] or '').replace('\n', ' ')
        rows.append(row)

    # we get the newest violations first, but we want to print them in order
    rows.reverse()

    with OutputFormat(output):
        print_table(['account_id', 'region', 'violation_type', 'instance_id', 'meta_info', 'comment', 'created_time'],
                    rows, titles={'created_time': 'Created'})


@cli.command('resolve-violations')
@click.option('--accounts', metavar='ACCOUNT_IDS',
              help='AWS account IDs to filter for (default: your configured accounts)')
@click.option('-s', '--since', default='1d', metavar='TIME_SPEC', help='Only show violations newer than')
@click.option('--severity')
@click.option('-t', '--type', metavar='VIOLATION_TYPE', help='Only show violations of given type')
@click.option('-r', '--region', metavar='AWS_REGION_ID', help='Filter by region')
@click.option('-l', '--limit', metavar='N', help='Limit number of results', type=int, default=20)
@click.argument('comment')
@click.pass_obj
def resolve_violations(config, comment, since, region, limit, **kwargs):
    '''Resolve violations'''
    url = config.get('url')
    if not url:
        raise click.ClickException('Missing configuration URL. Please run "stups configure".')

    kwargs['accounts'] = kwargs.get('accounts') or config.get('accounts')

    if not kwargs['accounts'] and not kwargs['type'] and not region:
        raise click.UsageError('At least one of --accounts, --type or --region must be specified')

    token = get_token()

    params = {'size': limit, 'sort': 'id,DESC'}
    params['since'] = parse_since(since)
    params.update(kwargs)
    r = request(url, '/api/violations', token, params=params)
    r.raise_for_status()
    data = r.json()

    for row in data['content']:
        if region and row['region'] != region:
            continue
        if row['comment']:
            # already resolved, skip
            continue
        with Action('Resolving violation {}/{} {} {}..'.format(row['account_id'], row['region'],
                    row['violation_type']['id'], row['id'])):
            r = session.post(url + '/api/violations/{}/resolution'.format(row['id']), data=comment,
                             headers={'Authorization': 'Bearer {}'.format(token)})
            r.raise_for_status()


def main():
    cli()
