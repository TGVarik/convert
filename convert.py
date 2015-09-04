#!/usr/bin/env python
# coding=utf-8
from __future__ import unicode_literals
from __future__ import print_function
import re
import os
from shutil import move
from logging import getLogger

import tmdbsimple as tmdb

from config import config
from newfinished import process_movie, process_tv

def blu_movies():
  folder = '/tank/Incoming'
  searcher = re.compile(
    r'^(\[(?P<collection>[^\]]+)\]\s*)?(?P<tmdb_id>\d+)\s?-(?P<title>.+?)$')
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if
                  os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  print('{:d} files found.'.format(len(files)))
  for f in files:
    match = searcher.search(os.path.splitext(os.path.basename(f))[0])
    if match:
      process_movie(f,
                    int(match.group('tmdb_id')),
                    collection=match.group('collection'),
                    crop=True,
                    keep_other_audio=True,
                    max_height=1080,
                    res_in_filename=True)
      process_movie(f,
                    int(match.group('tmdb_id')),
                    collection=match.group('collection'),
                    crop=True,
                    keep_other_audio=True,
                    max_height=720,
                    res_in_filename=True)
      process_movie(f,
                    int(match.group('tmdb_id')),
                    collection=match.group('collection'),
                    crop=True,
                    keep_other_audio=True,
                    max_height=480,
                    res_in_filename=True)
      move(f, f + '.done')
    else:
      log.error('Movie filename does not match pattern')

def main_movies():
  folder = '/tank/Incoming/'
  searcher = re.compile(
    r'^(\[(?P<collection>[^\]]+)\]\s*)?(?P<tmdb_id>\d+)\s?-(?P<title>.+?)(-(?P<feature_type>behindthescenes|deleted|interview|scene|trailer))?$')
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if
                  os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  print('{:d} files found.'.format(len(files)))
  for f in files:
    match = searcher.search(os.path.splitext(os.path.basename(f))[0])
    if match:
      if match.group('feature_type') is not None:
        process_movie(f,
                      int(match.group('tmdb_id')),
                      collection=match.group('collection'),
                      crop=True,
                      special_feature_title=match.group('title'),
                      special_feature_type=match.group('feature_type'))
      else:
        process_movie(f,
                      int(match.group('tmdb_id')),
                      collection=match.group('collection'),
                      crop=True,
                      keep_other_audio=True,
                      max_height=1080,
                      res_in_filename=True)
      move(f, f + '.done')
    else:
      log.error('Movie filename does not match pattern')


def main():
  folder = u'/tank/deluge/finished/Rick and Morty S1 Complete (Uncensored) (1920x1080) [Phr0stY]/'
  searcher = re.compile(r's(?P<season>\d\d?)e(?P<episode>\d\d)', re.I)
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if
                  os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  print('{:d} files found.'.format(len(files)))
  for f in files:
    match = searcher.search(os.path.basename(f))
    if match:
      process_tv(f,
                 275274,
                 int(match.group('season')),
                 int(match.group('episode')),
                 crop=True,
                 deint=False,
                 max_height=1080)
      move(f, f + '.done')


def retag_tv():
  folder = '/media/aristotle/retag/'
  show_id = 72116
  searcher = re.compile(r's(?P<season>\d+)e(?P<episode>\d+)', re.I)
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if
                  os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
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
  blu_movies()
