import datetime
import os

import click

import requests
import time
from zign.api import get_named_token
from clickclick import error, AliasedGroup, print_table, OutputFormat

import fullstop
import stups_cli.config
from fullstop.api import request


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
def cli(ctx, config_file):
    ctx.obj = stups_cli.config.load_config('fullstop')


@cli.command()
@click.option('--url', help='Pier One URL', metavar='URI')
@click.option('--realm', help='Use custom OAuth2 realm', metavar='NAME')
@click.option('-n', '--name', help='Custom token name (will be stored)', metavar='TOKEN_NAME', default='fullstop')
@click.option('-U', '--user', help='Username to use for authentication', envvar='fullstop_USER', metavar='NAME')
@click.option('-p', '--password', help='Password to use for authentication', envvar='fullstop_PASSWORD', metavar='PWD')
@click.pass_obj
def login(obj, url, realm, name, user, password):
    '''Login to fullstop.'''
    config = obj

    url = url or config.get('url')
    user = user or os.getenv('USER')

    while not url:
        url = click.prompt('Please enter the Fullstop URL')
        if not url.startswith('http'):
            url = 'https://{}'.format(url)

        try:
            requests.get(url, timeout=5)
        except:
            error('Could not reach {}'.format(url))
            url = None

        config['url'] = url

    stups_cli.config.store_config(config, 'fullstop')


def get_token():
    try:
        token = get_named_token(['uid'], None, 'fullstop', None, None)
    except:
        raise click.UsageError('No valid OAuth token named "fullstop" found. Please use "fullstop login".')
    return token


@cli.command()
@output_option
@click.pass_obj
def violations(config, output):
    '''Show violations'''
    token = get_token()

    r = request(config.get('url'), '/api/violations', token['access_token'])
    rows = [{'name': name} for name in sorted(r.json())]
    with OutputFormat(output):
        print_table(['name'], rows)



def main():
    cli()
