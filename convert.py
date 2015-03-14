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
from newfinished import process_movie, process_tv, safeify


def main_movies():
  folder = '/Volumes/Artemis/The Sound of Music'
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
        process_movie(f, int(match.group('tmdb_id')), collection=match.group('collection'), crop=True, tag_only=True)
      move(f, f + '.done')
    else:
      log.error('Movie filename does not match pattern')

def main():
  folder = u'/Volumes/storage/deluge/finished/The Closer'
  searcher = re.compile(r's(?P<season>\d\d)e(?P<episode>\d\d)', re.I)
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  print('{:d} files found.'.format(len(files)))
  #files.sort()
  for f in files:
    match = searcher.search(os.path.basename(f))
    if match:
      process_tv(f, 74875, int(match.group('season')), int(match.group('episode')), crop=True, deint=False, max_height=None, add_filters=['fieldmatch=mode=pcn_ub:combmatch=full:cthresh=8', 'yadif=deint=interlaced'])
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
        process_tv(f, show_id, season_number, episode_number, tag_only=True)
        move(f, f + '.done')

if __name__ == '__main__':
  tmdb.API_KEY = config['tmdb']
  from logs import setup_logging
  setup_logging('convert')
  log = getLogger()
  retag_tv()
