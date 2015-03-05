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
from logging import getLogger, LoggerAdapter
from tvdb_api import Tvdb
from ffmpeg import FfMpeg
from timer import Timer
from plex import refresh_plex
from cleaning import Cleaner
from config import config

log = None
tvdb_api_key = config['tvdb']
tmdb.API_KEY = config['tmdb']
plex_tv_section_folder = config['plex_tv_section']
oldmp4_folder = config['oldmp4_folder']
plex_movie_section_folder = config['plex_movie_section']
plex_tv_section_folder = '/Volumes/Artemis/Plex/TV Shows'
# oldmp4_folder = '/Volumes/ark/oldmp4'
plex_movie_section_folder = '/Volumes/Artemis/Plex/Movies/'

def check_exists(folder, file):
  if os.path.exists(os.path.join(folder, file)) and os.path.isfile(os.path.join(folder, file)):
    log.debug('Destination file already exists!')
    if os.path.exists(os.path.join(oldmp4_folder, file)):
      log.debug('File already exists in oldmp4')
      with Timer('Comparing files'):
        res = cmp(os.path.join(oldmp4_folder, file), os.path.join(folder, file))
      if res:
        log.debug('Files are identical, deleting Plex copy')
        os.remove(os.path.join(folder, file))
      else:
        log.debug('Files are different')
        with Timer('Renameing to timestamped backup in oldmp4'):
          os.rename(os.path.join(folder, file), os.path.join(oldmp4_folder, datetime.utcnow().strftime('%Y%m%dT%H%M%SZ-') + file))
    else:
      with Timer('Moving to oldmp4'):
        os.rename(os.path.join(folder, file), os.path.join(oldmp4_folder, file))

def process_movie(file_path, tmdb_id, collection=None, crop=False, special_feature_title=None, special_feature_type=None, tag_only=False):
  log = LoggerAdapter(getLogger(), {'identifier': os.path.basename(file_path)[:10]})
  if os.path.splitext(file_path)[1].lower() in ['.mkv', '.mp4', '.avi']:
    log.debug('TMDB ID: {:d}'.format(tmdb_id))
    illegal_chars = re.compile(r'[\\/:"*?<>|]')
    movie = tmdb.Movies(tmdb_id)
    response = movie.info()
    title = response['title']
    release = datetime.strptime(response['release_date'], '%Y-%m-%d')
    log.debug('Movie title: {:s}'.format(title))
    title_safe = ' '.join(illegal_chars.sub(repl=' ', string=title).split())
    log.debug('Safe movie title: {:s}'.format(title_safe))
    if collection is not None:
      destination_folder = os.path.join(plex_movie_section_folder, collection)
    else:
      destination_folder = os.path.join(plex_movie_section_folder)
    destination_folder = os.path.join(destination_folder, '{:s} ({:d})'.format(title_safe, release.year))
    if special_feature_title is not None and special_feature_type is not None:
      destination_filename = '{:s}-{:s}.mp4'.format(special_feature_title,special_feature_type)
    else:
      destination_filename = '{:s} ({:d}).mp4'.format(title_safe, release.year)
    log.info('Destination path: {:s}'.format(os.path.join(destination_folder, destination_filename)))
    if not os.path.exists(destination_folder):
      os.makedirs(destination_folder)
    check_exists(destination_folder, destination_filename)
    with Cleaner(title, temp_dir='/Volumes/Artemis/temp/') as c:
      target = file_path
      with Timer('Processing') as t:
        with FfMpeg(target, c) as n:
          if not tag_only:
            with Timer('Analyzing'):
              n.analyze()
            # if n.needs_aac_to_ac3_conversion:
            #   with Timer('Converting multichannel AAC to AC3'):
            #     n._multichannel_aac_to_ac3()
            # if crop:
            #   with Timer('Measuring video for autocrop'):
            #     n.autocrop()
            #     n.autoscale()
            # with Timer('Measuring volume'):
            #   n._multichannel_measure()
            with Timer('Converting'):
              n._convert_and_normalize()
          if special_feature_title is None and special_feature_type is None:
            with Timer('Tagging'):
              n.tag_movie(tmdb_id, collection)
          with Timer('Verifying faststart'):
            n.faststart()
          out = n.current_file
      c.timer_pushover(t)
      with Timer('Moving to Plex'):
        move(out, os.path.join(destination_folder, destination_filename))
    log.info('Processing complete')
    refresh_plex(source_type='movie')


def process_tv(file_path, show_id, season_number, episode_number, crop=False, keep_other_audio=False, deint=False):
  id = '{:05d}{:02d}{:03d}'.format(show_id, season_number, episode_number)
  log = LoggerAdapter(getLogger(), {'identifier': id})
  if os.path.splitext(file_path)[1].lower() in ['.mkv', '.mp4', '.avi']:
    log.debug('Show ID: {:d}, Season: {:d}, Episode: {:d}'.format(show_id, season_number, episode_number))
    illegal_chars = re.compile(r'[\\/:"*?<>|]')
    tvdb = Tvdb(apikey=tvdb_api_key, language='en', banners=True, actors=True)
    show = tvdb[show_id]
    show_name = show['seriesname']
    log.debug('Show name: {:s}'.format(show_name))
    show_name_safe = ' '.join(illegal_chars.sub(repl=' ', string=show_name).split())
    if show_name_safe[-1] == '.':
      show_name_safe = show_name_safe[:-1]
    log.debug('Safe show name: {:s}'.format(show_name_safe))
    with Cleaner('{:s} S{:02d}E{:02d}'.format(show_name_safe, season_number, episode_number), id) as c:
      season = show[season_number]
      episode = season[episode_number]
      episode_name = episode['episodename']
      log.debug('Episode name: {:s}'.format(episode_name))
      episode_name_safe = ' '.join(illegal_chars.sub(repl=' ', string=episode_name).split())
      log.debug('Safe episode name: {:s}'.format(episode_name_safe))
      destination_folder = os.path.join(plex_tv_section_folder, show_name_safe, 'Specials' if season_number == 0 else 'Season {:d}'.format(season_number))
      destination_filename = '{:s} - S{:02d}E{:02d} - {:s}.mp4'.format(show_name_safe, season_number, episode_number, episode_name_safe)
      log.info('Destination path: {:s}'.format(os.path.join(destination_folder, destination_filename)))
      if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)
      check_exists(destination_folder, destination_filename)
      target = file_path
      with Timer('Processing', id) as t:
        with FfMpeg(target, c, id) as n:
          with Timer('Analyzing', id):
            n.analyze(crop=crop, keep_other_audio=keep_other_audio)
          #with Timer('Checking interlacing', id):
            # n.detect_interlacing()
          # if n.needs_aac_to_ac3_conversion:
          #   with Timer('Converting multichannel AAC to AC3', id):
          #     n._multichannel_aac_to_ac3()
          # if crop:
          #   with Timer('Measuring video for autocrop', id):
          #     n.autocrop()
          #     n.autoscale()
          # with Timer('Measuring volume', id):
          #   n._multichannel_measure()
          with Timer('Converting', id):
            n._convert_and_normalize(deinterlace=deint)
          with Timer('Tagging', id):
            n.tag_tv(show_id, season_number, episode_number)
          with Timer('Verifying faststart', id):
            n.faststart()
          out = n.current_file
      c.timer_pushover(t)
      with Timer('Moving to Plex', id):
        move(out, os.path.join(destination_folder, destination_filename))
    log.info('Processing complete')
    refresh_plex(source_type='show')

def lotr():
  file = '/Volumes/Artemis/LOTR/The Lord of the Rings The Return of the King (2003).mp4'
  if os.path.exists(file):
    process_movie(file, 122, collection='The Lord of the Rings', crop=False, tag_only=True)
  else:
    print('file doesn\'t exist')

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
  folder = u'/Volumes/storage/deluge/finished/House Of Cards - Complete Season 2 720p/'
  searcher = re.compile(r's(?P<season>\d\d)e(?P<episode>\d\d)', re.I)
  #searcher = re.compile(r'(?P<season>\d)x(?P<episode>\d\d)', re.I)
  #searcher = re.compile(r'^(?P<season>\d)(?P<episode>\d\d)')
  files = []
  for root, dirs, fs in os.walk(folder):
    files.extend([os.path.join(root, f) for f in fs if os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi']])
  #files = glob(os.path.join(folder, '*.mp4'))
  #files = sorted(files, key=lambda f:int(searcher.search(os.path.basename(f)).group('episode')))
  print('{:d} files found.'.format(len(files)))
  for f in files:
    # searcher = re.compile(r'[sS](?P<season>\d\d)[eE](?P<episode>\d\d)')
    # searcher = re.compile(r's(?:eason\s)(?P<season>\d\d?)\s?e(?:pisode\s)(?P<episode>\d\d?)', re.I)
    match = searcher.search(os.path.basename(f))
    if match:
      process_tv(f, 262980, int(match.group('season')), int(match.group('episode')))
      move(f, f + '.done')
      #print '{:{width}s}: S{:02d}E{:02d}'.format(os.path.basename(f), int(match.group('season')), int(match.group('episode')), width=maxlen)
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
        tvdb = Tvdb(apikey=tvdb_api_key, language='en', banners=True, actors=True)
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
          destination_folder = os.path.join(plex_tv_section_folder, show_name_safe, 'Specials' if season_number == 0 else 'Season {:d}'.format(season_number))
          destination_filename = '{:s} - S{:02d}E{:02d} - {:s}.mp4'.format(show_name_safe, season_number, episode_number, episode_name_safe)
          log.info('Destination path: {:s}'.format(os.path.join(destination_folder, destination_filename)))
          if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
          if os.path.exists(os.path.join(destination_folder, destination_filename)) and os.path.isfile(os.path.join(destination_folder, destination_filename)):
            log.debug('Destination file already exists!')
            if os.path.exists(os.path.join(oldmp4_folder, destination_filename)):
              log.debug('File already exists in oldmp4')
              with Timer('Comparing files'):
                res = cmp(os.path.join(oldmp4_folder, destination_filename), os.path.join(destination_folder, destination_filename))
              if res:
                log.debug('Files are identical, deleting Plex copy')
                os.remove(os.path.join(destination_folder, destination_filename))
              else:
                log.debug('Files are different')
                with Timer('Renameing to timestamped backup in oldmp4'):
                  os.rename(os.path.join(destination_folder, destination_filename), os.path.join(oldmp4_folder, datetime.utcnow().strftime('%Y%m%dT%H%M%SZ-') + destination_filename))
            else:
              with Timer('Moving to oldmp4'):
                os.rename(os.path.join(destination_folder, destination_filename), os.path.join(oldmp4_folder, destination_filename))
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
  from logs import setup_logging
  setup_logging('convert')
  log = getLogger()
  main()
