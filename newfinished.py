#!/usr/bin/env python
# coding=utf-8
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import
import re
import os
import tmdbsimple as tmdb
import rarfile
from filecmp import cmp
from shutil import move
from datetime import datetime
from logging import getLogger, LoggerAdapter
from tvdb_api import Tvdb
from ffmpeg import FfMpeg, get_file_version
from timer import Timer
from plex import refresh_plex
from cleaning import Cleaner
from config import config
from twisted.internet import reactor
from deluge.ui.client import client
from time import sleep
from logs import setup_logging
from tempfile import gettempdir
from sys import argv
from psutil import process_iter

def safeify(name):
  safe_name = ' '.join(re.sub(pattern=r'[\\/:"*?<>|…]', repl=' ', string=name).split())
  safe_name = re.sub(pattern='’', repl='\'', string=safe_name)
  if safe_name[-1] == '.':
    safe_name = safe_name[:-1]
  return safe_name

temp_skip_list = [
  '/tank/Plex/Movies/How to Train Your Dragon/How to Train Your Dragon 2 (2014)/How to Train Your Dragon 2 (2014).1080p.mp4',
  '/tank/Plex/Movies/How to Train Your Dragon/How to Train Your Dragon 2 (2014)/How to Train Your Dragon 2 (2014).720p.mp4',
  '/tank/Plex/Movies/How to Train Your Dragon/How to Train Your Dragon 2 (2014)/How to Train Your Dragon 2 (2014).480p.mp4',
  '/tank/Plex/Movies/Harry Potter/Harry Potter and the Goblet of Fire (2005)/Harry Potter and the Goblet of Fire (2005).1080p.mp4',
  '/tank/Plex/Movies/Harry Potter/Harry Potter and the Goblet of Fire (2005)/Harry Potter and the Goblet of Fire (2005).720p.mp4',
  '/tank/Plex/Movies/Harry Potter/Harry Potter and the Goblet of Fire (2005)/Harry Potter and the Goblet of Fire (2005).480p.mp4',
  '/tank/Plex/Movies/The Hunt for Red October (1990)/The Hunt for Red October (1990).1080p.mp4',
  '/tank/Plex/Movies/The Hunt for Red October (1990)/The Hunt for Red October (1990).720p.mp4',
  '/tank/Plex/Movies/The Hunt for Red October (1990)/The Hunt for Red October (1990).480p.mp4',
  '/tank/Plex/Movies/Alien/Aliens (1986)/Aliens (1986).1080p.mp4',
  '/tank/Plex/Movies/Alien/Aliens (1986)/Aliens (1986).720p.mp4',
  '/tank/Plex/Movies/Alien/Aliens (1986)/Aliens (1986).480p.mp4',
  '/tank/Plex/Movies/Stargate (1994)/Stargate (1994).1080p.mp4',
  '/tank/Plex/Movies/Stargate (1994)/Stargate (1994).720p.mp4',
  '/tank/Plex/Movies/Stargate (1994)/Stargate (1994).480p.mp4',
  '/tank/Plex/Movies/Death Proof (2007)/Death Proof (2007).480p.mp4',
  '/tank/Plex/Movies/Lord of the Rings/The Lord of the Rings The Two Towers (2002)/The Lord of the Rings The Two Towers (2002).1080p.mp4',
  '/tank/Plex/Movies/Lord of the Rings/The Lord of the Rings The Two Towers (2002)/The Lord of the Rings The Two Towers (2002).720p.mp4',
  '/tank/Plex/Movies/Lord of the Rings/The Lord of the Rings The Two Towers (2002)/The Lord of the Rings The Two Towers (2002).480p.mp4',
  '/tank/Plex/Movies/Kill Bill/Kill Bill Vol. 2 (2004)/Kill Bill Vol. 2 (2004).1080p.mp4',
  '/tank/Plex/Movies/Kill Bill/Kill Bill Vol. 2 (2004)/Kill Bill Vol. 2 (2004).720p.mp4',
  '/tank/Plex/Movies/Kill Bill/Kill Bill Vol. 2 (2004)/Kill Bill Vol. 2 (2004).480p.mp4'
]

def check_exists(filepath, version):
  if os.path.exists(filepath) and os.path.isfile(filepath):
    if filepath in temp_skip_list:
      return 'skip'
    exists_version = get_file_version(filepath)
    if exists_version['video'] != version['video']:
      return 'replace'
    if exists_version['audio'] != version['audio']:
      # return 'audio'
      return 'replace'
    if exists_version['tags'] != version['tags']:
      # return 'retag'
      return 'replace'
    return 'skip'
  else:
    return False

def replace_existing(folder, filename):
  if os.path.exists(os.path.join(folder, filename)) and os.path.isfile(os.path.join(folder, filename)):
    outerlog.debug('Destination file already exists!')
    if os.path.exists(os.path.join(oldmp4_folder, filename)):
      outerlog.debug('File already exists in oldmp4')
      with Timer('Comparing files'):
        res = cmp(os.path.join(oldmp4_folder, filename), os.path.join(folder, filename))
      if res:
        outerlog.debug('Files are identical, deleting Plex copy')
        os.remove(os.path.join(folder, filename))
      else:
        outerlog.debug('Files are different')
        with Timer('Renameing to timestamped backup in oldmp4'):
          os.rename(os.path.join(folder, filename), os.path.join(oldmp4_folder, datetime.utcnow().strftime('%Y%m%dT%H%M%SZ-') + filename))
    else:
      with Timer('Moving to oldmp4'):
        os.rename(os.path.join(folder, filename), os.path.join(oldmp4_folder, filename))

def process_movie(file_path, tmdb_id, collection=None, special_feature_title=None, special_feature_type=None, crop=True, keep_other_audio=True, deint=False, tag_only=False, max_height=720, force_field_order=None, res_in_filename=False):
  ident = '{:<13s}'.format(os.path.basename(file_path)[:13])
  log = LoggerAdapter(getLogger(), {'identifier': ident})
  if os.path.splitext(file_path)[1].lower() in ['.mkv', '.mp4', '.avi']:
    log.debug('TMDB ID: {:d}'.format(tmdb_id))
    movie = tmdb.Movies(tmdb_id)
    response = movie.info()
    title = response['title']
    release = datetime.strptime(response['release_date'], '%Y-%m-%d')
    log.debug('Movie title: {:s}'.format(title))
    title_safe = safeify(title)
    log.debug('Safe movie title: {:s}'.format(title_safe))
    if collection is not None:
      destination_folder = os.path.join(plex_movie_section, collection)
    else:
      destination_folder = os.path.join(plex_movie_section)
    destination_folder = os.path.join(destination_folder, '{:s} ({:d})'.format(title_safe, release.year))

    if res_in_filename and max_height:
      fn = os.path.join(destination_folder, '{:s} ({:d}).{:d}p.mp4'.format(title_safe, release.year, max_height))
    else:
      fn = os.path.join(destination_folder, '{:s} ({:d}).mp4'.format(title_safe, release.year))
    exists = check_exists(fn, FfMpeg.version)

    if exists:
      if exists == 'skip':
        log.debug('skipping {:s}'.format(fn))
        return

    with Cleaner('{:s}{:s}'.format(title, ' {:d}p'.format(max_height) if max_height is not None else ''), ident) as c:
      target = file_path
      with Timer('Processing', ident) as t:
        with FfMpeg(target, c, ident) as n:
          if not tag_only:
            with Timer('Analyzing', ident):
              n.analyze(allow_crop=crop, keep_other_audio=keep_other_audio, max_height=max_height, deint=deint, force_field_order=force_field_order)
          height = n.default_video_stream['_scale']['height'] if '_scale' in n.default_video_stream else (n.default_video_stream['_crop']['height'] if '_crop' in n.default_video_stream else (n.default_video_stream['height']))
          width  = n.default_video_stream['_scale']['width']  if '_scale' in n.default_video_stream else (n.default_video_stream['_crop']['width']  if '_crop' in n.default_video_stream else (n.default_video_stream['width']))
          res = '1080p' if height > 720 or width > 1280 else ('720p' if height > 480 or width > 854 else '480p')
          if special_feature_title is not None and special_feature_type is not None:
            destination_filename = '{:s}-{:s}.mp4'.format(special_feature_title,special_feature_type)
          else:
            if res_in_filename:
              destination_filename = '{:s} ({:d}).{:s}.mp4'.format(title_safe, release.year, res)
            else:
              destination_filename = '{:s} ({:d}).mp4'.format(title_safe, release.year)
          log.info('Destination path: {:s}'.format(os.path.join(destination_folder, destination_filename)))
          if not tag_only:
            with Timer('Converting', ident):
              n.convert_and_normalize()
          if special_feature_title is None and special_feature_type is None:
            with Timer('Tagging', ident):
              n.tag_movie(tmdb_id, collection)
          with Timer('Verifying faststart', ident):
            n.faststart()
          out = n.current_file
          if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
          replace_existing(destination_folder, destination_filename)
      c.timer_pushover(t)
      with Timer('Moving to Plex', ident):
        move(out, os.path.join(destination_folder, destination_filename))
    log.info('Processing complete')
    refresh_plex(source_type='movie')

def process_tv(file_path, show_id, season_number, episode_number, crop=False, max_height=720.0, keep_other_audio=False, deint=False, tag_only=False, add_filters=None):
  ident = '{:06d}:{:02d}:{:03d}'.format(show_id, season_number, episode_number)
  log = LoggerAdapter(getLogger(), {'identifier': ident})
  if os.path.splitext(file_path)[1].lower() in ['.mkv', '.mp4', '.avi']:
    log.debug('Show ID: {:d}, Season: {:d}, Episode: {:d}'.format(show_id, season_number, episode_number))
    tvdb = Tvdb(apikey=config['tvdb'], language='en', banners=True, actors=True)
    show = tvdb[show_id]
    show_name = show['seriesname']
    log.debug('Show name: {:s}'.format(show_name))
    show_name_safe = safeify(show_name)
    log.debug('Safe show name: {:s}'.format(show_name_safe))
    with Cleaner('{:s} S{:02d}E{:02d}'.format(show_name_safe, season_number, episode_number), ident) as c:
      season = show[season_number]
      episode = season[episode_number]
      episode_name = episode['episodename']
      if episode_name is None:
        episode_name = ''
      log.debug('Episode name: {:s}'.format(episode_name))
      episode_name_safe = safeify(episode_name)
      log.debug('Safe episode name: {:s}'.format(episode_name_safe))
      destination_folder = os.path.join(plex_tv_section, show_name_safe, 'Specials' if season_number == 0 else 'Season {:d}'.format(season_number))
      destination_filename = '{:s} - S{:02d}E{:02d} - {:s}.mp4'.format(show_name_safe, season_number, episode_number, episode_name_safe)
      log.info('Destination path: {:s}'.format(os.path.join(destination_folder, destination_filename)))
      if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)
      replace_existing(destination_folder, destination_filename)
      target = file_path
      with Timer('Processing', ident) as t:
        with FfMpeg(target, c, ident) as n:
          if not tag_only:
            with Timer('Analyzing', ident):
              n.analyze(allow_crop=crop, keep_other_audio=keep_other_audio, max_height=max_height, deint=deint)
            with Timer('Converting', ident):
              n.convert_and_normalize(add_filters=add_filters)
          with Timer('Tagging', ident):
            n.tag_tv(show_id, season_number, episode_number)
          with Timer('Verifying faststart', ident):
            n.faststart()
          out = n.current_file
      c.timer_pushover(t)
      with Timer('Moving to Plex', ident):
        move(out, os.path.join(destination_folder, destination_filename))
    log.info('Processing complete')
    refresh_plex(source_type='show')

def cleanup():
  for f in temp_files:
    os.remove(f)
  client.disconnect()
  reactor.stop()

def on_remove_torrent(success):
  if success:
    outerlog.info('Torrent and data successfully removed.')
  else:
    outerlog.warn('Torrent and data could not be removed.')
  outerlog.info('Done, stopping.')
  cleanup()
  return

def ffmpeg_count():
  ffmpegs = 0
  for process in process_iter():
    if process.name() == 'ffmpeg':
      ffmpegs += 1
  return ffmpegs

def on_get_status(torrent):
  if 'label' in torrent:
    label = torrent['label']
    tag_regex = re.compile(r'^(?P<show_id>\d+)-(?P<season_number>\d+)-(?P<episode_number>\d+)$')
    tag = tag_regex.search(label)
    if tag:
      show_id = int(tag.group('show_id'))
      season_number = int(tag.group('season_number'))
      episode_number = int(tag.group('episode_number'))
      ident = '{:05d}{:02d}{:03d}'.format(show_id, season_number, episode_number)
      log = LoggerAdapter(getLogger(), {'identifier': ident})
      log.debug('Show ID: {:d}, Season: {:d}, Episode: {:d}'.format(show_id, season_number, episode_number))
      torrent_folder = torrent['move_completed_path']
      targets = []
      torrent_files = torrent['files']
      if len([f for f in torrent_files if f['path'][-3:].lower() == 'rar']) > 0:
        log.debug('Rar file detected')
        for f in [f for f in torrent_files if f['path'][-3:].lower() == 'rar']:
          with Timer('Reading rar file', ident):
            rar = rarfile.RarFile(os.path.join(torrent_folder, f['path']))
          video_files_in_rar = sorted([rf for rf in rar.infolist() if rf.filename[-3:].lower() in ['mkv', 'mp4', 'avi']], key=lambda r: r.file_size, reverse=True)
          with Timer('Extracting', ident):
            rar.extract(video_files_in_rar[0], temp_folder)
          temp_files.append(os.path.join(temp_folder, video_files_in_rar[0].filename))
          targets.append({'path': os.path.join(temp_folder, video_files_in_rar[0].filename), 'size': video_files_in_rar[0].file_size})
          log.debug('Added {:s} to targets list'.format(os.path.basename(video_files_in_rar[0].filename)))
          rar.close()
      elif len([f for f in torrent_files if f['path'][-3:].lower() in ['mkv', 'mp4', 'avi']]) > 0:
        log.debug('Video file detected')
        video_files_in_torrent = sorted([f for f in torrent_files if f['path'][-3:].lower() in ['mkv', 'mp4', 'avi']], key=lambda tor: tor['size'], reverse=True)
        targets.append({'path': video_files_in_torrent[0]['path'], 'size': video_files_in_torrent[0]['size']})
        log.debug('Added {:s} to targets list'.format(os.path.basename(video_files_in_torrent[0]['path'])))
      else:
        log.error('No eligible files found in torrent, stopping')
        cleanup()
        return
      target = sorted([t for t in targets], key=lambda d: d['size'], reverse=True)[0]
      ffmpegs = ffmpeg_count()
      if ffmpegs > 2:
        log.info('Waiting for other processes to finish')
        while ffmpegs > 2:
          sleep(60)
          ffmpegs = ffmpeg_count()
        log.debug('Done waiting')
      process_tv(os.path.join(torrent_folder, target['path']), show_id, season_number, episode_number, max_height=None)
      client.core.remove_torrent(torrentId, remove_data=True).addCallback(on_remove_torrent)
    else:
      outerlog.debug('Label \'{:s}\' not recognized'.format(label))
      cleanup()
  else:
    outerlog.debug('Torrent is not labeled')
    cleanup()

def on_get_status_failed(result):
  outerlog.error('Failed to get torrent status = {}'.format(repr(result)))
  cleanup()
  return

def on_connect_success(result):
  outerlog.debug('Connected to daemon with result {:d}'.format(result))
  outerlog.debug ('Fetching torrent status for id {:s}...'.format(torrentId))
  d = client.core.get_torrent_status(torrentId, ['label', 'files', 'move_completed_path'])
  d.addCallback(on_get_status)
  d.addErrback(on_get_status_failed)

def on_connect_fail(result):
  outerlog.error('Failed to connect to daemon - {}'.format(repr(result)))
  reactor.stop()

tvdb_api_key = config['tvdb']
tmdb.API_KEY = config['tmdb']
plex_tv_section = config['plex_tv_section']
oldmp4_folder = config['oldmp4_folder']
plex_movie_section = config['plex_movie_section']
rarfile.NEED_COMMENTS = 0
temp_folder = gettempdir()
outerlog = getLogger()

if __name__ == '__main__':
  temp_files = []
  torrentId = argv[1]
  setup_logging(os.path.join(config['log_path'], 'finished'))
  outerlog = getLogger()
  outerlog.info('finished.py called on {:s}'.format(argv[2]))
  outerlog.debug('Waiting ten seconds...')
  sleep(10)
  outerlog.debug('Connecting to daemon...')
  dd = client.connect(username='flexget', password='flexgetdeluge', host=config['deluge_host'])
  dd.addCallback(on_connect_success)
  dd.addErrback(on_connect_fail)
  reactor.run()
