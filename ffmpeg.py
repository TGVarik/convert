# coding=utf-8
from __future__ import unicode_literals
import math
import sys
if sys.version > '3':
  from urllib.request import urlretrieve
  from plistlib import dumps as dumps
else:
  from urllib import urlretrieve
  from plistlib import writePlistToString as dumps
import os
import re
import tmdbsimple as tmdb
from tvdb_api import Tvdb, tvdb_error
from subprocess import call, Popen, PIPE
import json
from logging import getLogger, LoggerAdapter
from config import config
from datetime import datetime
from requests.exceptions import Timeout

from qtfaststart import processor as qt

tvdb_api_key = config['tvdb']
tmdb.API_KEY = config['tmdb']
def _plist_to_string(root_object):
  return dumps(root_object)

def _command_to_string(command):
  if not isinstance(command, list):
    raise Exception('command_to_string takes a list, not a {:s}!'.format(type(command).__name__))
  return ' '.join(["'" + s + "'" if ' ' in s else s for s in command])

def _all_keys_to_lowercase(d):
  if isinstance(d, list):
    return [_all_keys_to_lowercase(v) for v in d]
  if isinstance(d, dict):
    return dict((k.lower(), _all_keys_to_lowercase(v)) for k, v in d.items())
  return d

def _join_and_ellipsize(elements, joiner, max_length, ellipsis=u'…'):
  s = joiner.join(elements)
  if len(s) > max_length:
    n = max([i for i in range(0, len(elements)) if len(joiner.join(elements[:i])) <= max_length - len(ellipsis)])
    s = joiner.join(elements[:n]) + ellipsis
  return s

class FfMpeg(object):
  def __init__(self, path, cleaner=None, id=None):
    if os.path.exists(path) and os.path.isfile(path):
      self.in_file = path
    self.log = getLogger()
    if id:
      self.log = LoggerAdapter(self.log, {'identifier': id})
    if cleaner is None:
      from tempfile import gettempdir
      class NullCleaner(object):
        def __init__(self):
          self.temp_dir = gettempdir()
        def add_path(self, path):
          pass
      self.cleaner = NullCleaner()
    else:
      self.cleaner = cleaner
    self.current_file = ''
    self.current_file_ext = ''
    self.current_file_basename = ''
    self.current_file_info = {}
    self.video_streams = []
    self.audio_streams = []
    self.subtitle_streams = []
    self.subtitle_files_to_add = []
    self._refresh(self.in_file)
    self.needs_aac_to_ac3_conversion = False

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    return False

  def _refresh(self, path):
    if not path is None:
      if os.path.exists(path) and os.path.isfile(path):
        root, ext = os.path.splitext(os.path.basename(path))
        if ext.lower() in ['.mkv', '.mp4', '.avi']:
          self.current_file = path
          self.current_file_ext = ext.lstrip('.')
          self.current_file_basename = root
          self.log.debug('Setting current file to \'{:s}\''.format(self.current_file))
          cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', self.current_file]
          proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
          out, err = proc.communicate()
          if err:
            raise Exception(err.decode())
          self.current_file_info = _all_keys_to_lowercase(json.loads(out))
          self.video_streams = sorted([s for s in self.current_file_info['streams'] if s['codec_type'] == 'video'], key=lambda s: s['index'])
          self.audio_streams = sorted([s for s in self.current_file_info['streams'] if s['codec_type'] == 'audio'], key=lambda s: s['index'])
          self.subtitle_streams = sorted([s for s in self.current_file_info['streams'] if s['codec_type'] == 'subtitle'], key=lambda s: s['index'])
          self.log.debug('Has video: {:d}, audio: {:d}, subtitle: {:d}'.format(len(self.video_streams), len(self.audio_streams), len(self.subtitle_streams)))

  def analyze(self, eng_only=True):
    if len(self.video_streams) < 1:
      raise Exception('No video streams detected!')
    elif len(self.video_streams) > 1:
      self.log.warning('More than one video stream')
      h264_streams = sorted([s for s in self.video_streams if s['codec_name'] == 'h264'], key=lambda s: s['index'])
      if len(h264_streams) > 0:
        self.log.debug('Using first h264 stream, ignoring others')
        self.video_streams = [h264_streams[0]]
      else:
        # really ought to filter for actual video streams, so as not to end up selecting a cover image
        self.log.debug('Using first video stream, ignoring others')
        self.video_streams = [self.video_streams[0]]
    if self.video_streams[0]['codec_name'] != 'h264': # or self.video_streams[0]['height'] > 720:
      self.video_streams[0]['_convert'] = True
    else:
      self.video_streams[0]['_convert'] = False
    if len(self.audio_streams) < 1:
      raise Exception('No audio streams detected!')
    for a in self.audio_streams:
      if 'tags' not in a:
        a['tags'] = {}
      if 'language' not in a['tags']:
        a['tags']['language'] = 'und'
    und_audio = sorted([s for s in self.audio_streams if ((s['tags']['language'] if 'language' in s['tags'] else 'und') if 'tags' in s else 'und') == 'und'], key=lambda s: s['index'])
    eng_audio = sorted([s for s in self.audio_streams if ((s['tags']['language'] if 'language' in s['tags'] else 'und') if 'tags' in s else 'und') == 'eng'], key=lambda s: s['index'])
    oth_audio = sorted([s for s in self.audio_streams if ((s['tags']['language'] if 'language' in s['tags'] else 'und') if 'tags' in s else 'und') not in ['und', 'eng']], key=lambda s: s['index'])
    if len(und_audio) > 0 and len(eng_audio) == 0 and len(oth_audio) == 0:
      und_audio[0]['tags']['language'] = 'eng'
      eng_audio.insert(0, und_audio.pop(0))
    for stream in und_audio:
      stream['_convert'] = False
      stream['_action'] = 'drop'
    if eng_only:
      for stream in oth_audio:
        stream['_convert'] = False
        stream['_action'] = 'drop'
    self.audio_streams = []
    self.audio_streams.extend(eng_audio)
    self.audio_streams.extend(oth_audio)
    self.audio_streams.extend(und_audio)
    if eng_only:
      for stream in [stream for stream in self.audio_streams if stream['tags']['language'] == 'eng']:
        if stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] == 2:
          stream['_action'] = 'copy'
          stream['_convert'] = False
        else:
          stream['_convert'] = True
          stream['_action'] = 'copy'
          for search in [search for search in self.audio_streams if search['tags']['language'] == 'eng' and search['index'] != stream['index']]:
            if search['codec_name'] in ['aac', 'libfdk_aac'] and search['channels'] == 2:
              stream['_convert'] = False
    else:
      for lang in [stream['tags']['language'] for stream in self.audio_streams if stream['tags']['language'] != 'und']:
        for stream in [stream for stream in self.audio_streams if stream['tags']['language'] == lang]:
          if stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] == 2:
            stream['_action'] = 'copy'
            stream['_convert'] = False
          else:
            stream['_convert'] = True
            stream['_action'] = 'copy'
            for search in [search for search in self.audio_streams if search['tags']['language'] == lang and search['index'] != stream['index']]:
              if search['codec_name'] in ['aac', 'libfdk_aac'] and search['channels'] == 2:
                stream['_convert'] = False
    if any([s['channels'] > 2 and s['codec_name'] in ['aac', 'libfdk_aac'] for s in self.audio_streams]):
      self.needs_aac_to_ac3_conversion = True
    else:
      self.needs_aac_to_ac3_conversion = False
    return self

  def crop(self, width, height, x, y):
    vs = self.video_streams[0]
    if vs['width'] > width or vs['height'] > height:
      vs['_convert'] = True
      vs['_crop'] = {'width': width, 'height': height, 'x': x, 'y': y}
      self.log.debug('Will crop to {width:d}:{height:d}:{x:d}:{y:d}'.format(**(vs['_crop'])))

  def autocrop(self, x_tolerance=4, y_tolerance=2):
    matches = []
    for i in range(1, int(math.floor(float(self.current_file_info['format']['duration']) / 240))):
      cmd = ['ffmpeg', '-hide_banner', '-ss', str(240 * i), '-i', self.current_file, '-vframes', '20', '-an', '-sn', '-vf:0', 'cropdetect=24:2:0', '-f', 'null', '-']
      self.log.debug(cmd)
      p = Popen(cmd, stdout=PIPE, stderr=PIPE)
      _, err = p.communicate()
      found = [m.groupdict() for m in re.finditer(r'crop=(?P<width>\d+):(?P<height>\d+):(?P<x>\d+):(?P<y>\d+)\D', err.decode('latin-1'))]
      matches.extend(found)
    match = sorted(matches, key=lambda mch: (int(mch['width']), int(mch['height'])), reverse=True)[0]
    vs = self.video_streams[0]
    if vs['width'] > int(match['width']) + x_tolerance or vs['height'] > int(match['height']) + y_tolerance:
      vs['_convert'] = True
      vs['_crop'] = {k: int(v) for k, v in match.items()}
      self.log.debug('Will crop to {width:d}:{height:d}:{x:d}:{y:d}'.format(**(vs['_crop'])))
    return self

  def autoscale(self, max_height=720, tolerance=0):
    max_width = int(max_height * 16 / 9)
    vs = self.video_streams[0]
    width = vs['width'] if '_crop' not in vs else vs['_crop']['width']
    height = vs['height'] if '_crop' not in vs else vs['_crop']['height']
    aspect = width / height
    if height > max_height + tolerance or width > max_width + tolerance:
      if aspect > 16/9:
        new_width = max_width
        new_height = max_width / aspect
      elif aspect < 16/9:
        new_height = max_height
        new_width = max_height * aspect
      else:
        new_height = max_height
        new_width = max_width
      vs['_convert'] = True
      vs['_scale'] = {'width': int(math.floor(new_width / 2) * 2), 'height': int(math.floor(new_height / 2) * 2)}
      self.log.debug('Will scale to {width:d}:{height:d}'.format(**(vs['_scale'])))
    return self

  def _convert_command(self, start=None, duration=None):
    cmd = ['ffmpeg', '-hide_banner', '-stats', '-y', '-v', 'quiet']
    inputs = ['-i', self.current_file]
    if start is not None:
      inputs.extend(['-ss', start])
    if duration is not None:
      inputs.extend(['-t', duration])
    maps = []
    converts = []
    input_index = 0
    video_index = 0
    audio_index = 0
    video_stream = self.video_streams[0]  # only taking one video stream for now
    maps.extend(['-map', '0:{:d}'.format(video_stream['index'])])
    if video_stream['_convert']:
      filters = []
      if '_crop' in video_stream:
        filters.append('crop={:d}:{:d}:{:d}:{:d}'.format(video_stream['_crop']['width'], video_stream['_crop']['height'], video_stream['_crop']['x'], video_stream['_crop']['y']))
      if '_scale' in video_stream:
        filters.append('scale={:d}:{:d}'.format(video_stream['_scale']['width'], video_stream['_scale']['height']))
      if len(filters) > 0:
        converts.extend(['-vf:{:d}'.format(video_index), ','.join(filters)])
      converts.extend(['-c:v:{:d}'.format(video_index), 'libx264', '-preset:v:{:d}'.format(video_index), 'fast', '-crf:v:{:d}'.format(video_index), '20'])
    else:
      converts.extend(['-c:v:{:d}'.format(video_index), 'copy'])
    for stream in self.audio_streams:
      if stream['_convert']:
        if stream['channels'] > 2:
          if input_index == 0:
            inputs.extend(['-request_channels', '2', '-i', self.current_file])
            input_index += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_index, stream['index'])])
        else:
          maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        if stream['codec_name'] in ['aac', 'libfdk_aac']:
          converts.extend(['-c:a:{:d}'.format(audio_index), 'aac', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
        else:
          converts.extend(['-c:a:{:d}'.format(audio_index), 'libfdk_aac', '-vbr:a:{:d}'.format(audio_index), '5', '-cutoff:a:{:d}'.format(audio_index), '18000', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
        audio_index += 1
      if stream['_action'] == 'copy':
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        converts.extend(['-c:a:{:d}'.format(audio_index), 'copy', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
        audio_index += 1
    cmd.extend(inputs)
    cmd.extend(maps)
    cmd.extend(converts)
    cmd.append('-sn')
    return cmd

  def convert(self):
    cmd = self._convert_command()
    dest = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'conv', 'mp4']))
    cmd.extend(['-f', 'mp4', dest])
    self.log.debug('calling ffmpeg')
    self.log.debug(_command_to_string(cmd))
    p = call(cmd)
    if p != 0:
      raise IOError('Conversion failed with exit code {:d}'.format(p))
    self.cleaner.add_path(dest)
    self._refresh(dest)
    return self

  def _multichannel_aac_to_ac3(self):
    if any([s['channels'] > 2 and s['codec_name'] in ['aac', 'libfdk_aac'] for s in self.audio_streams]):
      cmd = ['ffmpeg', '-hide_banner', '-v', 'quiet', '-stats', '-y', '-i', self.current_file]
      maps = []
      codecs = []
      video_index = 0
      audio_index = 0
      subtitle_index = 0
      for stream in self.video_streams:
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        codecs.extend(['-codec:v:{:d}'.format(video_index), 'copy'])
        video_index += 1
      for stream in self.audio_streams:
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        if stream['channels'] > 2 and stream['codec_name'] in ['aac', 'libfdk_aac']:
          codecs.extend(['-codec:a:{:d}'.format(audio_index), 'ac3'])
        else:
          codecs.extend(['-codec:a:{:d}'.format(audio_index), 'copy'])
        audio_index += 1
      for stream in self.subtitle_streams:
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        codecs.extend(['-codec:s:{:d}'.format(subtitle_index), 'copy'])
        subtitle_index += 1
      cmd.extend(maps)
      cmd.extend(codecs)
      dest = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'ac3', self.current_file_ext]))
      cmd.append(dest)
      self.log.debug(cmd)
      p = call(cmd)
      if p != 0:
        raise IOError('Converting multichannel AAC to AC3 failed with exit code {:d}'.format(p))
      self.cleaner.add_path(dest)
      self._refresh(dest)
      self.analyze()
    return self

  def _measure_loudness(self):
    cmd = ['ffmpeg', '-hide_banner', '-stats', '-i', self.current_file]
    maps = []
    filters = []
    audio_stream_counter = 0
    aac_streams = [s for s in self.audio_streams if s['codec_name'] in ['aac', 'libfdk_aac']]
    for stream in aac_streams:
      maps.extend(['-map', '0:{:d}'.format(stream['index'])])
      filters.extend(['-filter:a:{:d}'.format(audio_stream_counter), 'ebur128'])
      audio_stream_counter += 1
    cmd.extend(maps)
    cmd.extend(filters)
    cmd.extend(['-f', 'null', '-'])
    self.log.debug(_command_to_string(cmd))
    p = Popen(cmd, stdout=PIPE, stderr=PIPE)
    _, err = p.communicate()
    matches = [m.groupdict() for m in re.finditer(r'\[Parsed_ebur128_\d\s@\s0x(?P<position>[\da-f]{1,16})\]\sSummary:\s+Integrated\sloudness:\s+I:\s+(?P<loudness>-?\d\d.\d)\sLUFS', err.decode())]
    matches.sort(key=lambda m: int(m['position'], 16))
    if len(aac_streams) != len(matches):
      self.log.error('Whoops!')
      raise Exception('Whoops!')
    for n in range(0, len(matches)):
      stream = aac_streams[n]
      match = matches[n]
      stream['_loudness'] = float(match['loudness'])
      self.log.info('Stream {:d} has loudness {: >+5.1f}dB'.format(stream['index'], stream['_loudness']))

  def _multichannel_measure(self):
    cmd = ['ffmpeg', '-hide_banner', '-stats', '-request_channels', '2', '-i', self.current_file]
    maps = []
    filters = []
    audio_index = 0
    for stream in self.audio_streams:
      maps.extend(['-map', '0:{:d}'.format(stream['index'])])
      filters.extend(['-filter:a:{:d}'.format(audio_index), 'ebur128'])
      audio_index += 1
    cmd.extend(maps)
    cmd.extend(filters)
    cmd.extend(['-f', 'null', '-'])
    p = Popen(cmd, stdout=PIPE, stderr=PIPE)
    _, err = p.communicate()
    matches = [m.groupdict() for m in re.finditer(r'\[Parsed_ebur128_\d\s@\s0x(?P<position>[\da-f]{1,16})\]\sSummary:\s+Integrated\sloudness:\s+I:\s+(?P<loudness>-?\d\d.\d)\sLUFS', err.decode('latin-1'))]
    matches.sort(key=lambda m: int(m['position'], 16))
    for n in range(0, len(matches)):
      self.audio_streams[n]['_loudness'] = float(matches[n]['loudness'])
      self.log.info('Stream {:d} had loudness {: >+5.1f}dB'.format(self.audio_streams[n]['index'], self.audio_streams[n]['_loudness']))
    return self

  def _convert_and_normalize(self):
    video_index = 0
    audio_index = 0
    subtitle_index = 0
    cmd = ['ffmpeg', '-hide_banner', '-stats', '-y', '-v', 'quiet', '-fix_sub_duration']
    inputs = ['-i', self.current_file, '-request_channels', '2', '-i', self.current_file]
    maps = []
    converts = []

    video_stream = self.video_streams[0]  # only taking one video stream for now
    maps.extend(['-map', '0:{:d}'.format(video_stream['index'])])
    if video_stream['_convert']:
      filters = []
      if '_crop' in video_stream:
        filters.append('crop={:d}:{:d}:{:d}:{:d}'.format(video_stream['_crop']['width'], video_stream['_crop']['height'], video_stream['_crop']['x'], video_stream['_crop']['y']))
      if '_scale' in video_stream:
        filters.append('scale={:d}:{:d}'.format(video_stream['_scale']['width'], video_stream['_scale']['height']))
      if len(filters) > 0:
        converts.extend(['-vf:{:d}'.format(video_index), ','.join(filters)])
      converts.extend(['-c:v:{:d}'.format(video_index), 'libx264', '-preset:v:{:d}'.format(video_index), 'fast', '-crf:v:{:d}'.format(video_index), '20'])
    else:
      converts.extend(['-c:v:{:d}'.format(video_index), 'copy'])
    for stream in self.audio_streams:
      if stream['_action'] == 'copy':
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        converts.extend(['-c:a:{:d}'.format(audio_index), 'copy', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
        audio_index += 1
      if stream['_convert']:
        if stream['channels'] > 2:
          maps.extend(['-map', '1:{:d}'.format(stream['index'])])
        else:
          maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        if '_loudness' in stream:
          gain = -23.0 - stream['_loudness']
        else:
          gain = 0
        if abs(gain) > 0.5:
          self.log.debug('Stream {:d} needs {: >+5.1f}dB of gain'.format(stream['index'], gain))
          converts.extend(['-filter:a:{:d}'.format(audio_index), 'volume={:.1f}dB'.format(gain)])
        converts.extend(['-c:a:{:d}'.format(audio_index), 'libfdk_aac', '-vbr:a:{:d}'.format(audio_index), '5', '-cutoff:a:{:d}'.format(audio_index), '18000', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
        audio_index += 1
    for stream in self.subtitle_streams:
      maps.extend(['-map', '0:{:d}'.format(stream['index'])])
      converts.extend(['-c:s:{:d}'.format(subtitle_index), 'mov_text'])
      subtitle_index += 1
    cmd.extend(inputs)
    cmd.extend(maps)
    cmd.extend(converts)
    dest = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'norm', 'mp4']))
    cmd.extend(['-f', 'mp4', dest])
    self.log.debug(cmd)
    p = call(cmd)
    if p != 0:
      raise IOError('Normalization failed with exit code {:d}'.format(p))
    self.cleaner.add_path(dest)
    self._refresh(dest)
    return self


  def normalize(self):
    self._measure_loudness()
    video_stream_counter = 0
    audio_stream_counter = 0
    subtitle_stream_counter = 0
    cmd = ['ffmpeg', '-v', 'quiet', '-hide_banner', '-stats', '-y', '-i', self.current_file]
    maps = []
    converts = []
    for video_stream in self.video_streams:
      maps.extend(['-map', '0:{:d}'.format(video_stream['index'])])
      converts.extend(['-c:v:{:d}'.format(video_stream_counter), 'copy'])
      video_stream_counter += 1
    for audio_stream in self.audio_streams:
      maps.extend(['-map', '0:{:d}'.format(audio_stream['index'])])
      if audio_stream['codec_name'] in ['aac', 'libfdk_aac']:
        gain = -23.0 - audio_stream['_loudness']
      else:
        gain = 0
      if abs(gain) > 0.5:
        self.log.debug('Stream {:d} needs {: >+5.1f}dB of gain'.format(audio_stream['index'], gain))
        converts.extend(['-c:a:{:d}'.format(audio_stream_counter), 'libfdk_aac' if audio_stream['codec_name'] in ['aac', 'libfdk_aac'] else audio_stream['codec_name'], '-filter:a:{:d}'.format(audio_stream_counter), 'volume={:.1f}dB'.format(gain)])
        audio_stream_counter += 1
      else:
        self.log.debug('Stream {:d} needs {: >+5.1f}dB of gain'.format(audio_stream['index'], 0.0))
        converts.extend(['-c:a:{:d}'.format(audio_stream_counter), 'copy'])
        audio_stream_counter += 1
    for subtitle_stream in self.subtitle_streams:
      maps.extend(['-map', '0:{:d}'.format(subtitle_stream['index'])])
      converts.extend(['-c:s:{:d}'.format(subtitle_stream_counter), 'mov_text'])
      subtitle_stream_counter += 1
    cmd.extend(maps)
    cmd.extend(converts)
    normalized_file = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'norm', 'mp4']))
    cmd.extend(['-f', 'mp4', normalized_file])
    self.log.debug('Adjusting volume')
    self.log.debug(_command_to_string(cmd))
    p = call(cmd)
    if p != 0:
      raise IOError('Normalization failed with exit code {:d}'.format(p))
    self.cleaner.add_path(normalized_file)
    self._refresh(normalized_file)
    return self

  def _garnish(self, parsley):
    tagged_file = os.path.join(self.cleaner.temp_dir, u'.'.join([self.current_file_basename, 'tagged', self.current_file_ext]))
    cmd = ['AtomicParsley', self.current_file, '--metaEnema', '--output', tagged_file]
    for key, value in parsley.items():
      if key == 'rDNSatom':
        cmd.extend(['--{:s}'.format(key), value['value'], 'name={:s}'.format(value['name']), 'domain={:s}'.format(value['domain'])])
      else:
        cmd.extend(['--{:s}'.format(key), unicode(value).encode('utf-8')])
    self.log.debug(cmd)
    p = call(cmd)
    if p != 0:
      raise IOError('Tagging failed with exit code {:d}'.format(p))
    self.cleaner.add_path(tagged_file)
    self._refresh(tagged_file)

  def tag_movie(self, tmdb_id, collection=None):
    for i in range(0,4):
      try:
        movie = tmdb.Movies(tmdb_id)
        info = movie.info()
        credits = movie.credits()
        releases = movie.releases()
      except Timeout as e:
        if i < 3:
          self.log.warn('Unable to connect to TMDB, retrying ({:d} of 3'.format(i+1))
          continue
        else:
          self.log.fatal('Unable to connect to TMDB after 3 retries')
          raise e
      break
    cast = credits['cast']
    crew = credits['crew']
    release_date = datetime.strptime(info['release_date'], '%Y-%m-%d') if 'release_date' in info and info['release_date'] != '' else None
    # Buid the plist
    plist = {}
    plist_string = None

    if len(cast) > 0:
      plist['cast'] = [{'name': a['name']} for a in cast]
    if 'production_companies' in info and len(info['production_companies']) > 0:
      min_studio = min(s['id'] for s in info['production_companies'])
      plist['studio'] = [s['name'] for s in info['production_companies'] if s['id'] == min_studio][0]
    if len(crew) > 0:
      directors = [{'name': d['name']} for d in crew if d['job'] == 'Director' and d['name'] != '']
      if len(directors) > 0:
        plist['directors'] = directors
      writers = [{'name': w['name']} for w in crew if w['department'] == 'Writing' and w['name'] != '']
      if len(writers) > 0:
        plist['screenwriters'] = writers
      producers = [{'name': p['name']} for p in crew if p['job'] == 'Producer' and p['name'] != '']
      if len(producers) > 0:
        plist['producers'] = producers
    if plist != {}:
      plist_string = _plist_to_string(plist)
    # Build the parsley dict
    parsley = {}
    parsley['stik'] = u'Movie'
    if plist_string is not None:
      parsley['rDNSatom'] = {'name': 'iTunMOVI', 'domain': 'com.apple.iTunes', 'value': plist_string}
    if 'countries' in releases and len(releases['countries']) > 0:
      certifications = [c['certification'] for c in releases['countries'] if c['iso_3166_1'] == 'US' and c['certification'] != '']
      if len(certifications) > 0:
        parsley['contentRating'] = certifications[0]
    parsley['title'] = info['title']
    if len(cast) > 0:
      parsley['artist'] = _join_and_ellipsize([a['name'] for a in cast if a['name'] != ''], ', ', 255, '')
    if collection is not None:
      parsley['album'] = collection
      if release_date is not None:
        parsley['sortOrder'] = 'name "{:s} {:d}"'.format(collection, release_date.year)
    if 'genres' in info and len(info['genres']) > 0:
      parsley['genre'] = _join_and_ellipsize([g['name'] for g in info['genres'] if g['name'] != ''], ', ', 255, '')
    if release_date is not None:
      parsley['year'] = release_date.strftime('%Y-%m-%d')
    if 'tagline' in info and info['tagline'] != '':
      parsley['description'] = _join_and_ellipsize(re.sub('\/', '', info['tagline']).split(' '), ' ', 255)
    if 'overview' in info and info['overview'] != '':
      parsley['longdesc'] = re.sub('\/', '', info['overview'])
    if self.video_streams[0]['height'] > 720 or self.video_streams[0]['width'] > 1280:
      parsley['hdvideo'] = 2
    elif self.video_streams[0]['height'] > 480 or self.video_streams[0]['height'] > 854:
      parsley['hdvideo'] = 1
    else:
      parsley['hdvideo'] = 0
    if 'poster_path' in info and info['poster_path'] is not None:
      tmdb_config = tmdb.Configuration().info()
      poster_path = '{:s}{:s}{:s}'.format(tmdb_config['images']['base_url'], 'original', info['poster_path'])
      self.log.debug('Downloading temporary jpeg from {:s}'.format(poster_path))
      cover_file = os.path.join(self.cleaner.temp_dir, os.path.basename(poster_path))
      urlretrieve(poster_path, cover_file)
      self.cleaner.add_path(cover_file)
      parsley['artwork'] = cover_file
    self._garnish(parsley)
    return self

  def tag_tv(self, show_id, season_num, episode_num, dvdOrder=False):
    for i in range(0,4):
      try:
        tvdb = Tvdb(apikey=tvdb_api_key, language='en', banners=True, actors=True, dvdorder = dvdOrder)
        show = tvdb[show_id]
        episode = show[season_num][episode_num]
      except tvdb_error as e:
        if i < 3:
          self.log.warn('Unable to connect to TVDB, retrying ({:d} of 3)'.format(i+1))
          continue
        else:
          self.log.fatal('Unable to connect to TVDB after 3 retries')
          raise e
      break
    # Build the plist
    plist = {}
    plist_string = None
    if '_actors' in show.data and len(show['_actors']) > 0:
      plist['cast'] = [{'name': a['name']} for a in show['_actors'] if a['name'] is not None]
    if 'director' in episode and episode['director'] is not None:
      plist['directors'] = [{'name': d} for d in episode['director'].strip('|').split('|')]
    if 'writer' in episode and episode['writer'] is not None:
      plist['screenwriters'] = [{'name': w} for w in episode['writer'].strip('|').split('|')]
    if 'network' in show.data and show['network'] is not None:
      plist['studio'] = show['network']
    if plist != {}:
      plist_string = _plist_to_string(plist)
    # Build the parsley dict
    parsley = {}
    parsley['stik'] = u'TV Show'
    parsley['track'] = episode_num
    parsley['TVEpisodeNum'] = episode_num
    parsley['TVSeasonNum'] = season_num
    parsley['disk'] = 0
    if plist_string is not None:
      parsley['rDNSatom'] = {'name': 'iTunMOVI', 'domain': 'com.apple.iTunes', 'value': plist_string}
    if 'contentrating' in show.data and show.data['contentrating'] is not None:
      parsley['contentRating'] = show['contentrating']
    if 'episodename' in episode and episode['episodename'] is not None:
      parsley['title'] = episode['episodename']
      parsley['TVEpisode'] = u'{:02d} - {:s}'.format(episode_num, episode['episodename'])
    if '_actors' in show.data and len(show['_actors']) > 0:
      parsley['artist'] = _join_and_ellipsize([a['name'] for a in show['_actors']], ', ', 255, '')
    if 'seriesname' in show.data and show.data['seriesname'] is not None:
      parsley['albumArtist'] = show['seriesname']
      parsley['TVShowName'] = show['seriesname']
      if season_num == 0:
        parsley['album'] = '{:s}, Specials'.format(show['seriesname'])
      else:
        parsley['album'] = '{:s}, Season {:d}'.format(show['seriesname'], season_num)
    if 'genre' in show.data and show.data['genre'] is not None:
      parsley['genre'] = _join_and_ellipsize(show['genre'].strip('|').split('|'), ', ', 255, '')
    if 'firstaired' in episode and episode['firstaired'] is not None:
      parsley['year'] = episode['firstaired']
    if 'network' in show.data and show.data['network'] is not None:
      parsley['TVNetwork'] = show['network']
    if 'overview' in episode and episode['overview'] is not None:
      parsley['description'] = _join_and_ellipsize(episode['overview'].split(' '), ' ', 255)
      parsley['longdesc'] = episode['overview']
    if self.video_streams[0]['height'] > 720 or self.video_streams[0]['width'] > 1280:
      parsley['hdvideo'] = 2
    elif self.video_streams[0]['height'] > 480 or self.video_streams[0]['height'] > 854:
      parsley['hdvideo'] = 1
    else:
      parsley['hdvideo'] = 0
    if 'filename' in episode and episode['filename'] is not None:
      self.log.debug('Downloading temporary jpeg from {:s}'.format(episode['filename']))
      cover_file = os.path.join(self.cleaner.temp_dir, os.path.basename(episode['filename']))
      urlretrieve(episode['filename'], cover_file)
      self.cleaner.add_path(cover_file)
      parsley['artwork'] = cover_file
    self._garnish(parsley)
    return self

  def faststart(self):
    if not self._is_faststart():
      self.log.debug('Moving moov atom')
      faststart_file = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'faststart', 'mp4']))
      qt.process(self.current_file, faststart_file)
      self.cleaner.add_path(faststart_file)
      self.log.debug('moov atom moved successfully')
      self._refresh(faststart_file)
    return self

  def _is_faststart(self):
    if not os.path.exists(self.current_file):
      self.log.error('\'{:s}\' does not exist!'.format(self.current_file))
      raise IOError('{:s} does not exist!'.format(self.current_file))
    p = Popen(['AtomicParsley', self.current_file, '-T'], stdout=PIPE)
    self.log.debug('Testing for faststart')
    (out, err) = p.communicate()
    match = re.search('Atom moov @ (\d+) of', out)
    if int(match.group(1)) > 32:
      self.log.debug('moov offset is {:d}, not faststart'.format(int(match.group(1))))
      return False
    else:
      self.log.debug('moov offset is {:d}, is faststart'.format(int(match.group(1))))
      return True
