#!/usr/bin/env python
# coding=utf-8
from __future__ import unicode_literals
from __future__ import print_function
import re
import os
import tmdbsimple as tmdb
from filecmp import cmp
from shutil import move
from datetime import datetime
from logging import getLogger
from tvdb_api import Tvdb
from ffmpeg import FfMpeg
from timer import Timer
from plex import refresh_plex
from cleaning import Cleaner
from config import config
from newfinished import process_movie, process_tv


def main_movies():
  folder = '/Volumes/Artemis/LOTR'
  searcher = re.compile(r'^(\[(?P<collection>[^\]]+)\]\s*)?(?P<tmdb_id>\d+)\s?-(?P<title>.+?)(-(?P<feature_type>behindthescenes|deleted|interview|scene|trailer))?$')
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  # files = sorted(files, key=lambda f:int(searcher.search(os.path.basename(f)).group('tmdb_id')))
  print('{:d} files found.'.format(len(files)))
  for f in files:
    match = searcher.search(os.path.splitext(os.path.basename(f))[0])
    if match:
      if match.group('feature_type') is not None:
        process_movie(f, int(match.group('tmdb_id')), collection=match.group('collection'), crop=True, special_feature_title=match.group('title'), special_feature_type=match.group('feature_type'))
        # print('feature_type is not None: {:s}'.format(match.group('feature_type')))
      else:
        process_movie(f, int(match.group('tmdb_id')), collection=match.group('collection'), crop=False, tag_only=True)
      move(f, f + '.done')
    else:
      log.error('Movie filename does not match pattern')

def main():
  folder = u'/media/storage/deluge/finished/Vikings Season 1 Bluray/'
  searcher = re.compile(r's(?P<season>\d\d)e(?P<episode>\d\d)', re.I)
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  print('{:d} files found.'.format(len(files)))
  for f in files:
    match = searcher.search(os.path.basename(f))
    if match:
      process_tv(f, 260449, int(match.group('season')), int(match.group('episode')), crop=False, deint=False, max_height=None)
      move(f, f + '.done')
    #else:
      #print os.path.basename(f) + ': did not match!'
      #log.error('Couldn\'t find identifier in file name')

def retag_tv():
  folder = '/media/aristotle/retag/'
  show_id = 72116
  searcher = re.compile(r's(?P<season>\d)e(?P<episode>\d\d)', re.I)
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  print('{:d} files found.'.format(len(files)))
  for f in files:
    match = searcher.search(os.path.basename(f))
    if match:
      if os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']:
        season_number = int(match.group('season'))
        episode_number = int(match.group('episode'))
        log.debug('Show ID: {:d}, Season: {:d}, Episode: {:d}'.format(show_id, season_number, episode_number))
        illegal_chars = re.compile(r'[\\/:"*?<>|]')
        tvdb = Tvdb(apikey=config['tvdb'], language='en', banners=True, actors=True)
        show = tvdb[show_id]
        show_name = show['seriesname']
        log.debug('Show name: {:s}'.format(show_name))
        show_name_safe = ' '.join(illegal_chars.sub(repl=' ', string=show_name).split())
        log.debug('Safe show name: {:s}'.format(show_name_safe))
        with Cleaner('{:s} S{:02d}E{:02d}'.format(show_name_safe, season_number, episode_number)) as c:
          season = show[season_number]
          episode = season[episode_number]
          episode_name = episode['episodename']
          log.debug('Episode name: {:s}'.format(episode_name))
          episode_name_safe = ' '.join(illegal_chars.sub(repl=' ', string=episode_name).split())
          log.debug('Safe episode name: {:s}'.format(episode_name_safe))
          destination_folder = os.path.join(config['plex_tv_section'], show_name_safe, 'Specials' if season_number == 0 else 'Season {:d}'.format(season_number))
          destination_filename = '{:s} - S{:02d}E{:02d} - {:s}.mp4'.format(show_name_safe, season_number, episode_number, episode_name_safe)
          log.info('Destination path: {:s}'.format(os.path.join(destination_folder, destination_filename)))
          if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
          if os.path.exists(os.path.join(destination_folder, destination_filename)) and os.path.isfile(os.path.join(destination_folder, destination_filename)):
            log.debug('Destination file already exists!')
            if os.path.exists(os.path.join(config['oldmp4_folder'], destination_filename)):
              log.debug('File already exists in oldmp4')
              with Timer('Comparing files'):
                res = cmp(os.path.join(config['oldmp4_folder'], destination_filename), os.path.join(destination_folder, destination_filename))
              if res:
                log.debug('Files are identical, deleting Plex copy')
                os.remove(os.path.join(destination_folder, destination_filename))
              else:
                log.debug('Files are different')
                with Timer('Renameing to timestamped backup in oldmp4'):
                  os.rename(os.path.join(destination_folder, destination_filename), os.path.join(config['oldmp4_folder'], datetime.utcnow().strftime('%Y%m%dT%H%M%SZ-') + destination_filename))
            else:
              with Timer('Moving to oldmp4'):
                os.rename(os.path.join(destination_folder, destination_filename), os.path.join(config['oldmp4_folder'], destination_filename))
          target = f
          with Timer('Processing') as t:
            with FfMpeg(target, c) as n:
              with Timer('Tagging'):
                n.tag_tv(show_id, season_number, episode_number)
                n.faststart()
              out = n.current_file
          c.timer_pushover(t)
          with Timer('Moving to Plex'):
            move(out, os.path.join(destination_folder, destination_filename))
        log.info('Processing complete')
        refresh_plex(source_type='show')
        move(f, f + '.done')

if __name__ == '__main__':
  tmdb.API_KEY = config['tmdb']
  from logs import setup_logging
  setup_logging('convert')
  log = getLogger()
  main()
