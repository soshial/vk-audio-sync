# -*- coding: utf-8 -*-
import os
import sys
import urllib2
import shutil
import json
import codecs
import re
import HTMLParser

from mutagen.id3 import ID3, TIT2, TPE1, USLT, ID3NoHeaderError

import vk_api
import config

from progressbar import ProgressBar


def get_token(client_id, **user):
    if not user.get('scope'):
        user['scope'] = (['audio'])

    token, uid = vk_api.auth(
        user.get('username'),
        user.get('password'),
        client_id,
        ",".join(user.get('scope'))
    )

    return token, uid


def get_audio(token, uid):
    res = vk_api.call_method('audio.getCount', {'oid': uid}, token)
    audio_cnt = res.get('response')

    if audio_cnt and audio_cnt > 0:
        res = vk_api.call_method('audio.get', {'count': audio_cnt}, token)
        return res.get('response')


def get_audio_alb(token, uid, album_id):
    res = vk_api.call_method('audio.getCount', {'oid': uid}, token)
    audio_cnt = res.get('response')

    if audio_cnt and audio_cnt > 0:
        res = vk_api.call_method('audio.get', {'count': audio_cnt, 'album_id': album_id}, token)
        return res.get('response')


def clean_audio_tag(tag):
    h = HTMLParser.HTMLParser()
    tag = h.unescape(tag)
    tag = h.unescape(tag)  # need to unescape unescaped entities

    tag = re.sub(r'http://.[^\s]+', '', tag)  # remove any urls
    tag = tag.replace(' :)','')  # remove smiles

    tag = re.sub('’', '', tag).strip()  # quotation mark -> apostrophe
    ctag = re.compile(u'[^\w\s_\.,&#!?\-\'"`\/\|\[\]\(\)]', re.U)
    tag = ctag.sub('', tag).strip()  # kill most unusual symbols
    tag = re.sub(r'\s+', ' ', tag)  # remove long spaces

    return tag


def set_id3(filename, lyr_text, **track):
    try:
        mp3info = ID3(filename, v2_version=3)
    except ID3NoHeaderError:
        mp3info = ID3()

    mp3info['TIT2'] = TIT2(encoding=3, text=track.get('title'))
    mp3info['TPE1'] = TPE1(encoding=3, text=track.get('artist'))
    if lyr_text:
        mp3info[u'ENG||USLT'] = (USLT(encoding=3, lang=u'eng', desc=u'desc', text=lyr_text)) #::'eng'
    mp3info.save(filename, v2_version=3)


def save_tracks(filename, tracks):
    if not tracks:
        return

    fields = sorted(tracks[0].keys())

    with codecs.open(filename, 'w', 'utf-8') as fp:
        fp.write('%s\n' % ('\t'.join(fields)))

        for track in tracks:
            fp.write('%s\n' % ('\t'.join([unicode(track.get(f,"")) for f in fields])))


def open_tracks(filepath):
    with codecs.open(filepath, 'r', 'utf8') as fp:
        firstline = fp.next()
        fields = firstline.rstrip('\n').split('\t')
        for line in fp:
            track = dict(zip(fields, line.rstrip('\n').split('\t')))
            yield track


def download_tracks(tracks, token, uid, storage_path='files'):
    if tracks and not os.path.exists(storage_path):
        os.makedirs(storage_path)

    track_cnt = 1
    for track in tracks:
        track['aid'] = str(track.get('aid'))
        track['artist'] = clean_audio_tag(track.get('artist'))
        track['title'] = clean_audio_tag(track.get('title'))

        filename = os.path.basename(track.get('url')).split('?')[0]
        filepath = os.path.join(storage_path, "%s_%s" % (track.get('aid'), filename))

        if os.path.isfile(filepath):
            # todo support aborted downloads
            print 'Skipped "%(artist)s - %(title)s"' % (track)
            continue

        print '[%d/%d] ' % (track_cnt, len(tracks)) + 'Downloading "%(artist)s - %(title)s"...' % (track)

        try:
            req = urllib2.urlopen(track.get('url'))
            total = req.headers.get('content-length') or 0
            #print "total: %s" % (total)

            bar = None
            if total:
                bar = ProgressBar(maxval=int(total)).start()

            with open(filepath, 'wb') as fp:
                chunk_size = 16 * 1024
                loaded = 0

                for chunk in iter(lambda: req.read(chunk_size), ''):
                    fp.write(chunk)

                    if total:
                        loaded += len(chunk)
                        bar.update(loaded)

            if total:
                bar.finish()

            lyr_text = ''
            if track.get('lyrics_id'):
                print "Lyrics exist!"
                track['lyrics_id'] = clean_audio_tag(track.get('lyrics_id'))
                res = vk_api.call_method('audio.getLyrics', {'lyrics_id': track['lyrics_id']}, token)
                lyr_text = res.get('response')['text']
                with codecs.open(filepath + '.txt', 'w', encoding='utf-8') as lyr_file:
                    lyr_file.write(lyr_text)
                    lyr_file.close()
            set_id3(filepath, lyr_text, **track)
            track_cnt += 1

        except urllib2.HTTPError, err:
            print "HTTPError:", err

        except IOError, err:
            print "IOError:", err


def main():

    playlist = 'playlist.txt'
    tracks = []

    # authorization (needed for lyrics and albums)
    user = {
        'username': config.USERNAME,
        'password': config.PASSWORD,
        'scope': (['audio']),
    }
    client_id = config.CLIENT_ID
    token, uid = get_token(client_id, **user)

    if not os.path.isfile(playlist):
        tracks = get_audio(token, uid)
        save_tracks(playlist, tracks)
        res_albums = vk_api.call_method('audio.getAlbums', {'owner_id': uid}, token).get('response')[1:]
        for album in res_albums:
            print 'Saving album ' + album['title']+ str(album['album_id'])
            res_alb_tracks = get_audio_alb(token, uid, album['album_id'])
            save_tracks('alb_' + str(album['album_id']) + '_' + album['title'], res_alb_tracks)
    else:
        tracks = list(open_tracks(playlist))

    download_tracks(tracks, token, uid, 'files')

    print 'done.'


if __name__ == '__main__':
    main()

