# encoding: utf-8
import os
import urllib2
import time
import datetime
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

    tag = re.sub('’', '\'', tag).strip()  # quotation mark -> apostrophe
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
    """saves all tracks' info into a playlist file
    """
    if not tracks:
        return

    fields = sorted(tracks[0].keys())

    with codecs.open(filename, 'w', 'utf-8') as fp:
        fp.write('%s\n' % ('\t'.join(fields)))

        for track in tracks:
            fp.write('%s\n' % ('\t'.join([unicode(track.get(f,"")) for f in fields])))


def open_tracks(filepath):
    """Loads tracks from a file into a list
    """
    with codecs.open(filepath, 'r', 'utf8') as fp:
        firstline = fp.next()
        fields = firstline.rstrip('\n').split('\t')
        for line in fp:
            track = dict(zip(fields, line.rstrip('\n').split('\t')))
            track['duration'] = int(track['duration'])
            if track['genre'] != '':
                track['genre'] = int(track['genre'])
            track['aid'] = int(track['aid'])
            track['owner_id'] = int(track['owner_id'])
            yield track


def download_tracks(tracks, token, uid, login, storage_path='files'):
    # todo support of case, when tracks got renamed and lyrics got edited
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

            with open('temp.mp3', 'wb') as fp:
                chunk_size = 16 * 1024
                loaded = 0

                for chunk in iter(lambda: req.read(chunk_size), ''):
                    fp.write(chunk)

                    if total:
                        loaded += len(chunk)
                        bar.update(loaded)
            os.rename('temp.mp3', filepath)
            if total:
                bar.finish()

            if login:
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


def compare_playlists(tracks, previous_tracks):
    """Provides info about how many tracks were deleted, added and renamed compared to the previous playlist
    """
    import copy
    print 'Comparing saved playlist with the updated version'
    start_time = time.time()
    deleted = copy.deepcopy(previous_tracks)
    added = copy.deepcopy(tracks)
    changed = 0

    for trck_old in previous_tracks:
        for trck_new in tracks:
            if int(trck_new['aid']) == int(trck_old['aid']):
                deleted.remove(trck_old)
                added.remove(trck_new)
                if trck_new['artist'] != trck_old['artist'] or trck_new['title'] != trck_old['title']:
                    changed += 1
    print changed, ' tracks renamed'
    print len(added), ' new tracks added'
    for trck in added:
        print repr('    ' + trck['artist'] + u' — ' + trck['title']).decode("unicode-escape")
    print len(deleted), ' old tracks deleted'
    for trck in deleted:
        print repr('    ' + trck['artist'] + u' — ' + trck['title']).decode("unicode-escape")
    print 'Elapsed time on comparison', time.time()-start_time
    response = raw_input("Would you like to physically delete those tracks that were downloaded to your device but removed on VK? y/n:")
    if response.lower() == 'y':
        for trck in deleted:
            regex_match = re.search('/([a-z0-9]+\.mp3)\?extra=', trck['url'])
            if regex_match is None:
                print 'Can\'t find track filename in the URL'
            else:
                track_path = os.path.join('files', "%s_%s" % (trck.get('aid'), regex_match.group(1)))
                if os.path.isfile(track_path):
                    os.remove(track_path)
                    print 'Deleted!'
                else:
                    print 'No such file found!', trck['artist'], u'—', trck['title']
    print 'All new files will be downloaded automatically'


def main():
    new_playlist_file = 'playlist.txt'  # a temporary playlist file, that gets deleted after all tracks are downloaded
    playlists_folder = 'playlists'  # a folder for all previous playlist files
    if not os.path.exists(playlists_folder):
        os.makedirs(playlists_folder)
    today_date = str(datetime.date.today())
    prev_playlist_file = sorted(os.listdir(playlists_folder))[-1]
    print prev_playlist_file

    # authorization (needed for lyrics and albums)
    user = {
        'username': config.USERNAME,
        'password': config.PASSWORD,
        'scope': (['audio']),
    }
    client_id = config.CLIENT_ID
    token, uid = get_token(client_id, **user)
    print u'Connected to VK servers!'
    response = raw_input("Do you wish to download albums and lyrics? y/n: ")
    if response.lower() == 'y':
        login = True
    else:
        login = False

    if not os.path.isfile(new_playlist_file):
        # if no temporary @playlist file — we download the latest playlist version and compare with the previous one
        tracks = get_audio(token, uid)
        prev_tracks = list(open_tracks(os.path.join(playlists_folder, prev_playlist_file)))
        save_tracks(new_playlist_file, tracks)
        save_tracks(os.path.join(playlists_folder, today_date + '_main_' + new_playlist_file), tracks)  # a duplicate of the new playlist is saved for backup
        compare_playlists(tracks, prev_tracks)
        if login:
            # downloading separate album playlists
            print 'downloading album playlists'
            res_albums = vk_api.call_method('audio.getAlbums', {'owner_id': uid}, token).get('response')[1:]
            for album in res_albums:
                title = unicode(album['title']).strip()
                print u'Saving album ' + title.strip() + u' with id = ' + str(album['album_id'])
                res_alb_tracks = get_audio_alb(token, uid, album['album_id'])
                time.sleep(.500)  # accessing VK requires some timeout, otherwise request get ignored
                save_tracks(os.path.join(playlists_folder, u'albums', today_date + '_' + str(album['album_id']) + u'.txt'), res_alb_tracks)
    else:
        tracks = list(open_tracks(new_playlist_file))

    download_tracks(tracks, token, uid, login, 'files')
    os.remove(new_playlist_file)
    print 'All tracks downloaded.'


if __name__ == '__main__':
    main()