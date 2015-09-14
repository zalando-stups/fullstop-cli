import datetime

import click

import time
from zign.api import get_named_token
from clickclick import AliasedGroup, print_table, OutputFormat

import fullstop
import stups_cli.config
from fullstop.api import request
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
        token = get_named_token(['uid'], None, 'fullstop', None, None)
    except:
        raise click.UsageError('No valid OAuth token named "fullstop" found. Please use "zign token -n fullstop".')
    return token


def parse_since(s):
    return normalize_time(s, past=True).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


@cli.command()
@output_option
@click.option('--accounts')
@click.option('-s', '--since', default='1d')
@click.option('--severity')
@click.option('-t', '--type')
@click.option('-l', '--limit', help='Limit number of results', type=int, default=20)
@click.pass_obj
def violations(config, output, since, limit, **kwargs):
    '''Show violations'''
    url = config.get('url')
    if not url:
        raise click.ClickException('Missing configuration URL. Please run "stups configure".')

    token = get_token()

    params = {'size': limit, 'sort': 'id,DESC'}
    params['since'] = parse_since(since)
    params.update(kwargs)
    r = request(url, '/api/violations', token['access_token'], params=params)
    r.raise_for_status()
    data = r.json()

    rows = []
    for row in data['content']:
        row['violation_type'] = row['violation_type']['id']
        row['created_time'] = parse_time(row['created'])
        row['meta_info'] = (row['meta_info'] or '').replace('\n', ' ')
        rows.append(row)

    # we get the newest violations first, but we want to print them in order
    rows.reverse()

    with OutputFormat(output):
        print_table(['account_id', 'region', 'violation_type', 'instance_id', 'meta_info', 'comment', 'created_time'],
                    rows, titles={'created_time': 'Created'})


def main():
    cli()
