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
from copy import copy
from scipy import spatial

tvdb_api_key = config['tvdb']
tmdb.API_KEY = config['tmdb']

def get_ffprobe(filepath):
  cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', filepath]
  proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
  out, err = proc.communicate()
  if err:
    raise Exception(err.decode())
  return _all_keys_to_lowercase(json.loads(out))

def get_file_version(filepath):
  if os.path.isfile(filepath):
    cmd = ['AtomicParsley', filepath, '-t']
    version_matcher = re.compile('Atom\suuid=0c5c9153-0bd4-5e72-be75-92dfec8ab00c\s\(AP\suuid\sfor\s\"©inf\"\)\scontains:\sFFver(?P<version>\d+\.\d+\.\d+)', re.I)
    p = Popen(cmd, stdout=PIPE, stderr=PIPE)
    out, _ = p.communicate()
    found = version_matcher.search(out.decode('latin-1'))
    if found:
      parts = found.groupdict()['version'].split('.')
      return {
        'video': int(parts[0]),
        'audio': int(parts[1]),
        'tags' : int(parts[2])
      }
  return None

def _plist_to_string(root_object):
  return dumps(root_object).decode('utf-8')

def _command_to_string(command):
  if not isinstance(command, list):
    raise Exception('command_to_string takes a list, not a {:s}!'.format(type(command).__name__))
  l = ["'{:s}'".format(s) if ' ' in s else s for s in [s.decode('utf-8') for s in command]]
  result = re.sub('[\n\t]+', '', ' '.join(l))
  return result

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

def _get_scaled(dims, mw, mh):
  w = dims['width']
  h = dims['height']
  if mw is not None and mh is not None and (w > mw or h > mh):
    ma = float(mw) / float(mh)
    a = float(w) / float(h)
    ow = mw if a >= ma else math.ceil(mh*a)
    oh = math.ceil(mw/a) if a > ma else mh
  else:
    ow = w
    oh = h
  return {'width': int(ow), 'height': int(oh)}

def _get_max_width(max_height):
  if max_height == 1080:
    return 1920
  elif max_height == 720:
    return 1280
  elif max_height == 480:
    return 854
  else:
    return None

def _get_delta(max_height):
  if max_height == 1080:
    return 6
  elif max_height == 720:
    return 22
  elif max_height == 480:
    return 46
  else:
    return None

def _is_aligned(point, mw, mh):
  scaled = _get_scaled(point, mw, mh)
  return ((point['width'] * point['height'] * 3.0 / 2.0) % 16 == 0 and
          (scaled['width'] * scaled['height'] * 3.0 / 2.0) % 16 == 0 and
          point['width'] % 2 == 0 and point['height'] % 2 == 0 and
          scaled['width'] % 2 == 0 and scaled['height'] % 2 == 0)

def _new_fix_crop(original, max_height, crop=None):
  if crop is None:
    crop = {'x': 0, 'y': 0, 'width': original['width'], 'height': original['height']}

  max_width = _get_max_width(max_height)
  delta = _get_delta(max_height)

  points = [{'width': w, 'height': h} for w in range(crop['width'], crop['width'] + delta + 1, 2) for h in range(crop['height'], crop['height'] + delta + 1, 2)]
  fpoints = [pt for pt in points if _is_aligned(pt, max_width, max_height)]
  tree = spatial.KDTree([[p['width'], p['height']] for p in fpoints])
  res = tree.data[tree.query([crop['width'], crop['height']])[1]]

  newcrop = {'x': crop['x'] - ((res[0] - crop['width']) / 2),
             'y': crop['y'] - ((res[1] - crop['height']) / 2),
             'width': res[0], 'height': res[1]}
  newscale = _get_scaled(newcrop, max_width, max_height)
  newpad = {'x': 0, 'y': 0, 'width': original['width'], 'height': original['height']}
  while newcrop['x'] < 0:
    newcrop['x'] += 4
    newpad['x'] += 4
    newpad['width'] += 4
  while newcrop['y'] < 0:
    newcrop['y'] += 2
    newpad['y'] += 2
    newpad['width'] += 2
  while newcrop['width'] + newcrop['x'] > newpad['width']:
    newpad['width'] += 4
  while newcrop['height'] + newcrop['y'] > newpad['height']:
    newpad['height'] += 4

  result = {}
  if newpad['x'] != 0 or newpad['y'] != 0 or newpad['width'] != original['width'] or newpad['height'] != original['height']:
    result['pad'] = newpad
  if newcrop['x'] != 0 or newcrop['y'] != 0 or newcrop['width'] != original['width'] or newcrop['height'] != original['height']:
    result['crop'] = newcrop
  if newscale['width'] != newcrop['width'] or newscale['height'] != newcrop['height']:
    result['scale'] = newscale

  return result

def _fix_crop(original, max_height, crop=None):
  result = {}
  if crop is None:
    crop = {'x': 0, 'y': 0, 'width': original['width'], 'height': original['height']}
  if crop['width'] % 2 == 1:
    crop['width'] += 1
  scaled = _get_scaled(crop, _get_max_width(max_height), max_height)

  size = copy(original)
  if size['width'] != crop['width'] or size['height'] != crop['height']:
    result['crop'] = crop
    size = copy(crop)
  if size['width'] != scaled['width'] or size['height'] != scaled['height']:
    result['scale'] = scaled

  return result

class FfMpeg(object):
  version = {
    'video': 0,
    'audio': 1,
    'tags' : 1
  }
  def __init__(self, filepath, cleaner=None, ident=None):
    if os.path.exists(filepath) and os.path.isfile(filepath):
      self.in_file = filepath
    self.log = getLogger()
    if ident:
      self.log = LoggerAdapter(self.log, {'identifier': ident})
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
          self.current_file_info = get_ffprobe(self.current_file)
          self.video_streams = sorted([s for s in self.current_file_info['streams'] if s['codec_type'] == 'video' and s['codec_name'] != 'mjpeg'], key=lambda st: st['index'])
          self.audio_streams = sorted([s for s in self.current_file_info['streams'] if s['codec_type'] == 'audio'], key=lambda st: st['index'])
          self.subtitle_streams = sorted([s for s in self.current_file_info['streams'] if s['codec_type'] == 'subtitle'], key=lambda st: st['index'])
          self.log.debug('Has video: {:d}, audio: {:d}, subtitle: {:d}'.format(len(self.video_streams), len(self.audio_streams), len(self.subtitle_streams)))

  def _analyze_audio(self, keep_others):
    # TODO: Always request_channels 2 when codec_name is ac3 or dca!
    if len(self.audio_streams) < 1:
      raise Exception('No audio streams detected!')
    default = [s for s in self.audio_streams if s['channels'] == max(self.audio_streams, key=lambda i:i['channels'])['channels']]
    if len(default) == 0:
      default = [s for s in self.audio_streams if s['codec_name'] in ['ac3', 'dca']]
    elif len(default) > 1:
      temp = [s for s in default if s['codec_name'] in ['ac3', 'dca']]
      if len(temp) > 0:
        default = temp
    if len(default) == 0:
      default = [s for s in self.audio_streams]
    default = default[0]
    if default['channels'] > 2 and default['codec_name'] in ['aac', 'libfdk_aac']:
      self.needs_aac_to_ac3_conversion = True
    default['_default'] = True
    default['_measure'] = True
    default['_copy'] = False if (default['codec_name'] in ['aac', 'libfdk_aac'] and default['channels'] > 2) \
                                or (default['codec_name'] not in ['dca', 'ac3', 'libfdk_aac', 'aac']) else True
    default['_convert'] = False if default['codec_name'] in ['aac', 'libfdk_aac'] and default['channels'] <= 2 else True
    self.default_audio_stream = default
    for stream in self.audio_streams:
      if '_default' not in stream:
        stream['_default'] = False
      if '_measure' not in stream:
        stream['_measure'] = True if keep_others and stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] <= 2 else False
      if '_copy' not in stream:
        stream['_copy'] = True if keep_others else False
      if '_convert' not in stream:
        stream['_convert'] = False
      if 'tags' not in stream:
        stream['tags'] = {}
      if 'language' not in stream['tags']:
        stream['tags']['language'] = 'eng'
      if stream['tags']['language'] == 'und':
        stream['tags']['language'] = 'eng'
    self.audio_streams = sorted(self.audio_streams, key=lambda st: (-st['_default'], st['index']))
    if any([s['_measure'] for s in self.audio_streams]):
      self._measure_loudness()

  def _analyze_crop_scale_deint(self, crop, max_height, deint, force_field_order):
    cropmatches = []
    deintmatches = []
    filters = []
    rcrop = re.compile(r'crop=(?P<width>\d+):(?P<height>\d+):(?P<x>\d+):(?P<y>\d+)\D', re.I)
    rdeint = re.compile(r'Multi\sframe\sdetection:\sTFF:\s*(?P<tff>\d+)\sBFF:\s*(?P<bff>\d+)\sProgressive:\s*(?P<pro>\d+)\sUndetermined:\s*(?P<und>\d+)', re.I)
    if deint and force_field_order is None:
      filters.append('idet')
    if crop:
      filters.append('cropdetect=24:2:0')
    if crop or (deint and force_field_order is None):
      n = int(math.floor(float(self.current_file_info['format']['duration']) / 240))
      if n > 1:
        for i in range(1,n):
          cmd = ['ffmpeg',
                 '-hide_banner',
                 '-ss', str(240 * i),
                 '-i', self.current_file,
                 '-vframes', '20',
                 '-map', '0:{:d}'.format(self.default_video_stream['index']),
                 '-an',
                 '-sn',
                 '-vf:0', ','.join(filters),
                 '-f', 'null',
                 '-']
          self.log.debug(_command_to_string(cmd))
          p = Popen(cmd, stdout=PIPE, stderr=PIPE)
          _, err = p.communicate()
          found = [m.groupdict() for m in rcrop.finditer(err.decode('latin-1'))]
          cropmatches.extend(found)
          if deint:
            found = [m.groupdict() for m in rdeint.finditer(err.decode('latin-1'))]
            deintmatches.extend(found)
      else:
        cmd = ['ffmpeg',
               '-hide_banner',
               '-i', self.current_file,
               '-map', '0:{:d}'.format(self.default_video_stream['index']),
               '-an',
               '-sn',
               '-vf:0', 'cropdetect=24:2:0',
               '-f', 'null',
               '-']
        self.log.debug(_command_to_string(cmd))
        p = Popen(cmd, stdout=PIPE, stderr=PIPE)
        _, err = p.communicate()
        if crop:
          found = [m.groupdict() for m in rcrop.finditer(err.decode('latin-1'))]
          cropmatches.extend(found)
        if deint:
          found = [m.groupdict() for m in rdeint.finditer(err.decode('latin-1'))]
          deintmatches.extend(found)
    if crop:
      match = {k: int(v) for k,v in max(cropmatches, key=lambda ma:(int(ma['width']), int(ma['height']))).items()}
      results = _new_fix_crop(self.default_video_stream, max_height=max_height, crop=match)
    else:
      results = _new_fix_crop(self.default_video_stream, max_height=max_height)

    if deint:
      if force_field_order is None:
        deint_data = {
          'TFF': sum([int(m['tff']) for m in deintmatches]),
          'BFF': sum([int(m['bff']) for m in deintmatches]),
          'Progressive': sum([int(m['pro']) for m in deintmatches]),
          'Undetermined': sum([int(m['und']) for m in deintmatches])
        }
        totalframes = float(sum(deint_data.values()))
        detectedframes = float(sum([v for k,v in deint_data.items() if k != 'Undetermined']))
        deint_data = {k: [float(v) / totalframes, float(v)/detectedframes] for k, v in deint_data.items()}
        fieldorder, pct = max(deint_data.items(), key=lambda x:x[1][0])
        if fieldorder in ['TFF', 'BFF', 'Progressive'] and pct[0] >= 0.75 and pct[1] >= 0.95:
          self.default_video_stream['_fieldorder'] = fieldorder
        else:
          self.default_video_stream['_fieldorder'] = 'Undetermined'
        self.log.info('Field order is: {:s}'.format(self.default_video_stream['_fieldorder']))
      else:
        self.default_video_stream['_fieldorder'] = force_field_order
        self.log.info('Field order forced to: {:s}'.format(self.default_video_stream['_fieldorder']))

    if 'pad' in results:
      self.log.info('Will pad to {width:d}:{height:d}:{x:d}:{y:d}'.format(**(results['pad'])))
      self.default_video_stream['_pad'] = results['pad']
    if 'crop' in results:
      self.log.info('Will crop to {width:d}:{height:d}:{x:d}:{y:d}'.format(**(results['crop'])))
      self.default_video_stream['_crop'] = results['crop']
    if 'scale' in results:
      self.log.info('Will scale to {width:d}:{height:d}'.format(**(results['scale'])))
      self.default_video_stream['_scale'] = results['scale']

  def _analyze_video(self, allow_crop, max_height, deint, force_field_order):
    if len(self.video_streams) < 1:
      raise Exception('No video streams detected!')
    elif len(self.video_streams) > 1:
      self.log.warning('More than one video stream')
      h264_streams = sorted([s for s in self.video_streams if s['codec_name'] == 'h264'], key=lambda st: st['index'])
      if len(h264_streams) > 0:
        self.log.debug('Using first h264 stream, ignoring others')
        self.default_video_stream = h264_streams[0]
      else:
        self.log.debug('Using first video stream, ignoring others')
        self.default_video_stream = self.video_streams[0]
    else:
      self.default_video_stream = self.video_streams[0]
    if allow_crop or deint or max_height is not None:
      self._analyze_crop_scale_deint(crop=allow_crop, max_height=max_height, deint=deint, force_field_order=force_field_order)
    vs = self.default_video_stream
    if vs['codec_name'] != 'h264' or '_pad' in vs or '_crop' in vs or '_scale' in vs or (deint and vs['_fieldorder'] in ['TFF', 'BFF']):
      vs['_convert'] = True
    else:
      vs['_convert'] = False

  def analyze(self, allow_crop=True, max_height=None, keep_other_audio=False, deint=False, force_field_order=None):
    self._max_height = max_height
    self._analyze_video(allow_crop=allow_crop, max_height=max_height, deint=deint, force_field_order=force_field_order)
    self._analyze_audio(keep_others=keep_other_audio)

  def _build_aac_to_ac3_pipeline(self):
    aac_multi_streams = 0
    cmd = ['ffmpeg', '-hide_banner', '-v', 'quiet', '-i', self.current_file]
    maps = []
    converts = []
    audio_index = 0
    for stream in [stream for stream in self.audio_streams if stream['_measure'] == True]:
      if stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] > 2:
        aac_multi_streams += 1
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        converts.extend(['-c:a:{:d}'.format(audio_index), 'ac3'])
    if len(maps) > 0:
      converts.extend(['-vn', '-sn'])
      cmd.extend(maps)
      cmd.extend(converts)
      cmd.extend(['-f', 'ac3', '-'])
    return cmd

  def _measure_loudness(self):
    cmd = ['ffmpeg', '-hide_banner', '-stats']
    inputs = []
    maps = []
    filters = []
    input_count = 0
    input_indices = {'main': None, 'aac_to_ac3': None, 'request_channels': None}
    aac_to_ac3_audio_index = 0
    audio_index = 0
    for stream in [stream for stream in self.audio_streams if stream['_measure'] == True]:
      if stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] > 2:
        if input_indices['aac_to_ac3'] is None:
          pre = self._build_aac_to_ac3_pipeline()
          pre.append('|')
          pre.extend(cmd)
          cmd = pre
          inputs.extend(['-f', 'ac3', '-request_channels', '2', '-i', '-'])
          input_indices['aac_to_ac3'] = input_count
          input_count += 1
        maps.extend(['-map', '{:d}:{:d}'.format(input_indices['aac_to_ac3'], aac_to_ac3_audio_index)])
        filters.extend(['-filter:a:{:d}'.format(audio_index), 'ebur128'])
        aac_to_ac3_audio_index += 1
        audio_index += 1
      elif stream['channels'] > 2 or stream['codec_name'] in ['ac3', 'dca']:
        if input_indices['request_channels'] is None:
          inputs.extend(['-request_channels', '2', '-i', self.current_file])
          input_indices['request_channels'] = input_count
          input_count += 1
        maps.extend(['-map', '{:d}:{:d}'.format(input_indices['request_channels'], stream['index'])])
        filters.extend(['-filter:a:{:d}'.format(audio_index), 'ebur128'])
        audio_index += 1
      else:
        if input_indices['main'] is None:
          inputs.extend(['-i', self.current_file])
          input_indices['main'] = input_count
          input_count += 1
        maps.extend(['-map', '{:d}:{:d}'.format(input_indices['main'], stream['index'])])
        filters.extend(['-filter:a:{:d}'.format(audio_index), 'ebur128'])
        audio_index += 1
    cmd.extend(inputs)
    cmd.extend(maps)
    cmd.extend(filters)
    cmd.extend(['-f', 'null', '-'])
    self.log.debug(_command_to_string(cmd))
    p = Popen(cmd, stdout=PIPE, stderr=PIPE)
    _, err = p.communicate()
    output = err.decode('latin-1')
    summary_finder = re.compile(r'\[Parsed_ebur128_\d\s@\s0x(?P<position>[\da-f]{1,16})\]\sSummary:\s+Integrated\sloudness:\s+I:\s+(?P<loudness>-?\d\d.\d)\sLUFS')
    matches = [m for m in summary_finder.finditer(output)]
    matches.sort(key=lambda ma: int(ma.groupdict()['position'], 16))

    # if len(matches) > len([s for s in self.audio_streams if s['_measure'] == True]):
    #   # Input stream #0:1 frame changed from rate:48000 fmt:fltp ch:2 chl:stereo to rate:48000 fmt:fltp ch:6 chl:5.1(side)
    #   change_finder = re.compile(r'Input\sstream\s#(?P<input>\d):(?P<stream>\d)\sframe\schanged\sfrom\srate:(?P<old_rate>\d+)\sfmt:(?P<old_fmt>\S+)\sch:(?P<old_ch>\d)\schl:(?P<old_chl>\S+)\sto\srate:(?P<new_rate>\d+)\sfmt:(?P<new_fmt>\S+)\sch:(?P<new_ch>\d)\schl:(?P<new_chl>\S+)\s')
    #   changes = [m for m in change_finder.finditer(output)]
    #   if len(changes) > 0:
    #     for input in OrderedDict.fromkeys([m.group('input') for m in changes]).keys():
    #       for stream in OrderedDict.fromkeys([m.group('stream') for m in changes if m.group('input') == input]).keys():
    #         stream_changes = [change for change in changes if change.group('input') == input and change.group('stream') == stream]
    #         for i in range(len(stream_changes)):
    #           if i + 1 == len(stream_changes):
    #             stream_changes[i]._percent = len(output) - stream_changes[i].end()
    #           else:
    #             stream_changes[i]._percent = stream_changes[i + 1].start() - stream_changes[i].end()
    #
    #   else:
    #     throw
    for n in range(0, len(matches)):
      try:
        stream = [s for s in self.audio_streams if s['_measure'] == True][n]
      except IndexError as e:
        self.log.error('{} : {}'.format(len([s for s in self.audio_streams if s['_measure'] == True]), n))
        for match in matches:
          self.log.error(repr(match))
        self.log.error('assuming discontinuity; continuing...')
        stream = [s for s in self.audio_streams if s['_measure'] == True][n - 1]
        # raise e
      stream['_loudness'] = float(matches[n].group('loudness'))
      self.log.info('Stream {:d} had loudness {:.1f}dB'.format(stream['index'], stream['_loudness']))
      if abs(-23 - stream['_loudness']) > 1:
        stream['_gain'] = -23 - stream['_loudness']
        self.log.info('Stream {:d} needs {:+.1f}dB of gain'.format(stream['index'], stream['_gain']))
        if stream['_copy'] and stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] <= 2:
          stream['_convert'] = True
          stream['_copy'] = False
    return self

  def convert_and_normalize(self, add_filters=None):
    cmd = ['ffmpeg', '-hide_banner', '-stats', '-y']#, '-v', 'quiet']
    inputs = []
    maps = []
    filters = []
    converts = []
    input_count = 0
    input_indices = {'main': None, 'aac_to_ac3': None, 'request_channels': None, 'aac_request_channels': None}
    aac_to_ac3_audio_index = 0
    audio_index = 0
    ### Video
    if input_indices['main'] is None:
      inputs.extend(['-i', self.current_file])
      input_indices['main'] = input_count
      input_count += 1
    maps.extend(['-map', '{:d}:{:d}'.format(input_indices['main'], self.default_video_stream['index'])])
    if self.default_video_stream['_convert']:
      f = []
      if add_filters is not None:
        f.extend(add_filters)
      if '_fieldorder' in self.default_video_stream and self.default_video_stream['_fieldorder'] in ['TFF', 'BFF']:
        f.append('idet')
        f.append('yadif=0:{:d}:1'.format(0 if self.default_video_stream['_fieldorder'] == 'TFF' else 1))
      if '_pad' in self.default_video_stream:
        f.append('pad={width:d}:{height:d}:{x:d}:{y:d}'.format(**(self.default_video_stream['_pad'])))
      if '_crop' in self.default_video_stream:
        f.append('crop={width:d}:{height:d}:{x:d}:{y:d}'.format(**(self.default_video_stream['_crop'])))
      if '_scale' in self.default_video_stream:
        f.append('scale={width:d}:{height:d}'.format(**(self.default_video_stream['_scale'])))
      if len(f) > 0:
        filters.extend(['-filter:v:0', ','.join(f)])
      converts.extend(['-c:v:0', 'libx264', '-preset:v:0', 'fast', '-crf:v:0', '21'])
    else:
      converts.extend(['-c:v:0', 'copy'])
    ### Audio
    for stream in self.audio_streams:
      if stream['codec_name'] in ['aac', 'libfdk_aac'] and stream['channels'] > 2:
        if stream['_copy']:
          if input_indices['aac_to_ac3'] is None:
            if input_indices['aac_request_channels'] is None:
              pre = self._build_aac_to_ac3_pipeline()
              if len(pre) > 0:
                pre.append('|')
                pre.extend(cmd)
                cmd = pre
            inputs.extend(['-f', 'ac3', '-i', '-'])
            input_indices['aac_to_ac3'] = input_count
            input_count += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_indices['aac_to_ac3'], aac_to_ac3_audio_index)])
          converts.extend(['-c:a:{:d}'.format(audio_index), 'copy', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
          audio_index += 1
        if stream['_convert']:
          if input_indices['aac_request_channels'] is None:
            if input_indices['aac_to_ac3'] is None:
              pre = self._build_aac_to_ac3_pipeline()
              if len(pre) > 0:
                pre.append('|')
                pre.extend(cmd)
                cmd = pre
            inputs.extend(['-f', 'ac3', '-request_channels', '2', '-i', '-'])
            input_indices['aac_request_channels'] = input_count
            input_count += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_indices['aac_request_channels'], aac_to_ac3_audio_index)])
          if '_gain' in stream:
            filters.extend(['-filter:a:{:d}'.format(audio_index), 'volume={:.1f}dB'.format(stream['_gain'])])
          converts.extend(['-c:a:{:d}'.format(audio_index), 'libfdk_aac', '-vbr:a:{:d}'.format(audio_index), '5', '-cutoff:a:{:d}'.format(audio_index), '20000', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
          audio_index += 1
        if stream['_copy'] or stream['_convert']:
          aac_to_ac3_audio_index += 1
      elif stream['channels'] > 2 or stream['codec_name'] in ['ac3', 'dca']:
        if stream['_copy']:
          if input_indices['main'] is None:
            inputs.extend(['-i', self.current_file])
            input_indices['main'] = input_count
            input_count += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_indices['main'], stream['index'])])
          converts.extend(['-c:a:{:d}'.format(audio_index), 'copy', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
          audio_index += 1
        if stream['_convert']:
          if input_indices['request_channels'] is None:
            inputs.extend(['-request_channels', '2', '-i', self.current_file])
            input_indices['request_channels'] = input_count
            input_count += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_indices['request_channels'], stream['index'])])
          if '_gain' in stream:
            filters.extend(['-filter:a:{:d}'.format(audio_index), 'volume={:.1f}dB'.format(stream['_gain'])])
          converts.extend(['-c:a:{:d}'.format(audio_index), 'libfdk_aac', '-vbr:a:{:d}'.format(audio_index), '5', '-cutoff:a:{:d}'.format(audio_index), '20000', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
          audio_index += 1
      else:
        if stream['_copy']:
          if input_indices['main'] is None:
            inputs.append(['-i', self.current_file])
            input_indices['main'] = input_count
            input_count += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_indices['main'], stream['index'])])
          converts.extend(['-c:a:{:d}'.format(audio_index), 'copy', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
          audio_index += 1
        if stream['_convert']:
          if input_indices['main'] is None:
            inputs.append(['-i', self.current_file])
            input_indices['main'] = input_count
            input_count += 1
          maps.extend(['-map', '{:d}:{:d}'.format(input_indices['main'], stream['index'])])
          if '_gain' in stream:
            filters.extend(['-filter:a:{:d}'.format(audio_index), 'volume={:.1f}dB'.format(stream['_gain'])])
          converts.extend(['-c:a:{:d}'.format(audio_index), 'libfdk_aac', '-vbr:a:{:d}'.format(audio_index), '5', '-cutoff:a:{:d}'.format(audio_index), '20000', '-metadata:s:a:{:d}'.format(audio_index), 'language={:s}'.format(stream['tags']['language'])])
          audio_index += 1
        ### Subtitle
    converts.append('-sn')
    ### Final
    cmd.extend(inputs)
    cmd.extend(maps)
    cmd.extend(filters)
    cmd.extend(converts)
    dest = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'norm', 'mp4']))
    cmd.extend(['-f', 'mp4', dest])
    self.log.debug(_command_to_string(cmd))
    p = call(cmd)
    if p != 0:
      raise IOError('Normalization failed with exit code {:d}'.format(p))
    self.cleaner.add_path(dest)
    self._refresh(dest)
    return self

  def _garnish(self, parsley):
    parsley['information'] = 'zzzzFFVer{video:d}.{audio:d}.{tags:d}'.format(**(FfMpeg.version))
    tagged_file = os.path.join(self.cleaner.temp_dir, '.'.join([self.current_file_basename, 'tagged', self.current_file_ext]))
    cmd = ['AtomicParsley', self.current_file, '--metaEnema', '--output', tagged_file]
    for key, value in parsley.items():
      if key == 'rDNSatom':
        cmd.extend(['--{:s}'.format(key), value['value'], 'name={:s}'.format(value['name']), 'domain={:s}'.format(value['domain'])])
      elif key == 'sortOrder':
        cmd.append('--{:s}'.format(key))
        cmd.extend([unicode(v) for v in value])
      else:
        cmd.extend(['--{:s}'.format(key), unicode(value)])
    self.log.debug(_command_to_string(cmd))
    cmd = [v.encode('utf-8') for v in cmd]
    try:
      p = Popen(cmd, stdout=PIPE, stderr=PIPE)
    except TypeError as e:
      for c in cmd:
        self.log.error('{} : {}'.format(type(c).__name__, c))
      raise e
    (out, err) = p.communicate()
    if p.returncode != 0:
      raise IOError('Tagging failed with exit code {:d}\n\n{:s}\n\n{:s}'.format(p.returncode, out, err))
    self.cleaner.add_path(tagged_file)
    self._refresh(tagged_file)

  def tag_movie(self, tmdb_id, collection=None):
    for i in range(0,4):
      try:
        movie = tmdb.Movies(tmdb_id)
        info = movie.info()
        cred = movie.credits()
        releases = movie.releases()
      except Timeout as e:
        if i < 3:
          self.log.warning('Unable to connect to TMDB, retrying ({:d} of 3'.format(i+1))
          continue
        else:
          self.log.critical('Unable to connect to TMDB after 3 retries')
          raise e
      break
    cast = cred['cast']
    crew = cred['crew']
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
    parsley = {'stik': u'Movie'}
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
        parsley['sortOrder'] = ['name', '{:s} {:d}'.format(collection, release_date.year)]
    if 'genres' in info and len(info['genres']) > 0:
      parsley['genre'] = _join_and_ellipsize([g['name'] for g in info['genres'] if g['name'] != ''], ', ', 255, '')
    if release_date is not None:
      parsley['year'] = release_date.strftime('%Y-%m-%d')
    if 'tagline' in info and info['tagline'] != '':
      parsley['description'] = _join_and_ellipsize(re.sub('/', '', info['tagline']).split(' '), ' ', 255)
    if 'overview' in info and info['overview'] != '':
      parsley['longdesc'] = re.sub('/', '', info['overview'])
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
        tvdb = Tvdb(apikey=tvdb_api_key, language='en', banners=True, actors=True, dvdorder=dvdOrder)
        show = tvdb[show_id]
        episode = show[season_num][episode_num]
      except tvdb_error as e:
        if i < 3:
          self.log.warning('Unable to connect to TVDB, retrying ({:d} of 3)'.format(i+1))
          continue
        else:
          self.log.critical('Unable to connect to TVDB after 3 retries')
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
    parsley = {'stik': u'TV Show', 'track': unicode(episode_num), 'TVEpisodeNum': unicode(episode_num), 'TVSeasonNum': unicode(season_num), 'disk': '0'}
    if plist_string is not None:
      parsley['rDNSatom'] = {'name': 'iTunMOVI', 'domain': 'com.apple.iTunes', 'value': plist_string}
    if 'contentrating' in show.data and show.data['contentrating'] is not None:
      parsley['contentRating'] = show['contentrating']
    if 'episodename' in episode and episode['episodename'] is not None:
      parsley['title'] = episode['episodename']
      parsley['TVEpisode'] = '{:02d} - {:s}'.format(episode_num, episode['episodename'])
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
      parsley['hdvideo'] = '2'
    elif self.video_streams[0]['height'] > 480 or self.video_streams[0]['height'] > 854:
      parsley['hdvideo'] = '1'
    else:
      parsley['hdvideo'] = '0'
    if 'filename' in episode and episode['filename'] is not None:
      self.log.debug('Downloading temporary jpeg from {:s}'.format(episode['filename']))
      cover_file = os.path.join(self.cleaner.temp_dir, os.path.basename(episode['filename']))
      urlretrieve(episode['filename'], cover_file)
      self.cleaner.add_path(cover_file)
      parsley['artwork'] = cover_file
      if os.path.splitext(cover_file)[1].lower() == '.jpg':
        with open(cover_file, 'r+b') as f:
          fourbytes = [ord(b) for b in f.read(4)]
          if fourbytes[0] == 0xff and fourbytes[1] == 0xd8 and fourbytes[2] == 0xff and fourbytes[3] != 0xe0:
            f.seek(3)
            f.write(chr(0xe0))
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
