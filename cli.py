import click
import re
import os
from newfinished import process_tv
from shutil import move
from config import config
import tmdbsimple as tmdb
from logging import getLogger

@click.group()
def cli():
  pass

@click.command()
@click.argument('folder', type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True))
@click.argument('tvdb_id', type=click.INT)
def series(folder, tvdb_id):
  searcher = re.compile(r's(?P<season>\d\d?)e(?P<episode>\d\d)', re.I)
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if
                  os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi'] and
                  searcher.search(os.path.basename(f)) is not None])
  print('{:d} files found.'.format(len(files)))

  for f in sorted(files, key=lambda f: (int(searcher.search(os.path.basename(f)).group('season')), int(searcher.search(os.path.basename(f)).group('episode')))):
    match = searcher.search(os.path.basename(f))
    if match:
      process_tv(f,
                 tvdb_id,
                 int(match.group('season')),
                 int(match.group('episode')),
                 crop=True,
                 deint=True,
                 max_height=1080)
      move(f, f + '.done')

cli.add_command(series)

if __name__ == '__main__':
  tmdb.API_KEY = config['tmdb']
  from logs import setup_logging

  setup_logging('cli')
  log = getLogger()
  cli()
