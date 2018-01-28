import datetime as dt
import email
import email.header
import email.policy
import encodings
import hashlib
import json
import mimetypes
import re
import uuid
from email.message import MIMEPart
from email.utils import formatdate, getaddresses, parsedate_to_datetime

import chardet

from . import html, log

aliases = {
    # Seems Google used gb2312 in some subjects, so there is another symbol
    # instead of dash, because of next bug:
    # https://bugs.python.org/issue24036
    'gb2312': 'gbk',
    # @naspeh got such encoding in my own mailbox
    'cp-1251': 'cp1251',
}
encodings.aliases.aliases.update(aliases)


class BinaryPolicy(email.policy.Compat32):
    """+
    Dovecot understands UTF-8 encoding, so let's save parsed messages
    without sanitizing.
    """
    def _sanitize_header(self, name, value):
        return value

    def _fold(self, name, value, sanitize=None):
        return '%s: %s%s' % (name, value, self.linesep)

    def fold_binary(self, name, value):
        folded = self._fold(name, value)
        return folded.encode('utf8', 'surrogateescape')


policy = BinaryPolicy()


def binary(txt, mimetype='text/plain'):
    msg = MIMEPart(policy)
    msg.set_type(mimetype)
    msg.add_header('Content-Transfer-Encoding', 'binary')
    msg.set_payload(txt, 'utf-8')
    return msg


def link(msgids):
    msgid = gen_msgid('link')
    msg = MIMEPart(policy)
    msg.add_header('Subject', 'Dummy: linking threads')
    msg.add_header('References', ' '.join(msgids))
    msg.add_header('Message-Id', msgid)
    msg.add_header('From', 'mailur@link')
    msg.add_header('Date', formatdate())
    return msg


def parsed(raw, uid, time, mids):
    def try_decode(raw, charsets, label=''):
        txt = err = None
        charsets = [aliases.get(c, c) for c in charsets if c]
        for c in charsets:
            try:
                txt = raw.decode(c)
                break
            except UnicodeDecodeError as e:
                err = 'error on %r: [UnicodeDecodeError] %s' % (label, e)
        return txt, err

    def decode_bytes(raw, charset, label):
        if not raw:
            return ''

        txt = None
        charset = charset and charset.lower()
        if charset == 'unknown-8bit' or not charset:
            # first trying to decode with charsets detected in message
            txt = try_decode(raw, charsets)[0] if charsets else None
            if txt:
                return txt

            # trying chardet
            detected = chardet.detect(raw)
            charset = detected['encoding']
            if charset:
                charset = charset.lower()
            else:
                charset = charsets[0] if charsets else 'utf8'

        txt, err = try_decode(raw, [charset], label)
        if txt:
            # if decoded without errors add to potential charsets list
            charsets.append(charset)
        if not txt:
            log.info('## UID=%s %s', uid, err)
            meta['errors'].append(err)
            txt = raw.decode(charset, 'replace')
        return txt

    def decode_header(raw, label):
        if not raw:
            return ''

        parts = []
        for raw, charset in email.header.decode_header(raw):
            if isinstance(raw, str):
                txt = raw
            else:
                txt = decode_bytes(raw, charset, label)
            parts += [txt]

        header = ''.join(parts)
        header = re.sub('\s+', ' ', header)
        return header

    def attachment(part, content, path):
        label = '%s(%s)' % (part.get_content_type(), path)
        item = {'size': len(content), 'path': path}
        item.update({
            k: v for k, v in (
                ('content-id', part.get('Content-ID')),
                ('filename', decode_header(part.get_filename(), label)),
            ) if v
        })
        if not item.get('filename'):
            ctype = part.get_content_type()
            ext = mimetypes.guess_extension(ctype) or 'txt'
            item['filename'] = 'unknown-%s%s' % (path, ext)
        return item

    def parse_part(part, path=''):
        htm, files = '', []
        ctype = part.get_content_type()
        if ctype.startswith('message/'):
            content = part.as_bytes()
            files = [attachment(part, content, path)]
            return htm, files
        elif part.get_filename():
            content = part.get_payload(decode=True)
            files = [attachment(part, content, path)]
            return htm, files
        elif part.is_multipart():
            idx, parts = 0, []
            for m in part.get_payload():
                idx += 1
                path_ = '%s.%s' % (path, idx) if path else str(idx)
                htm_, files_ = parse_part(m, path_)
                if htm_:
                    parts.append((htm_, m.get_content_type() == 'text/html'))
                files += files_

            if part.get_content_subtype() == 'alternative':
                htm_ = [c for c, is_htm in parts if is_htm]
                if htm_:
                    htm = htm_[0]
                elif parts:
                    htm = parts[0][0]
            else:
                htm = '<hr>'.join(c for c, h in parts if c)
            return htm, files

        if ctype.startswith('text/'):
            content = part.get_payload(decode=True)
            charset = part.get_content_charset()
            label = '%s(%s)' % (ctype, path)
            content = decode_bytes(content, charset, label)
            content = content.rstrip()
            if ctype == 'text/html':
                htm = content
            else:
                htm = content and html.from_text(content)
        else:
            content = part.get_payload(decode=True)
            files = [attachment(part, content, path)]
        return htm, files

    # "email.message_from_bytes" uses "email.policy.compat32" policy
    # and it's by intention, because new policies don't work well
    # with real emails which have no encodings, badly formated addreses, etc.
    orig = email.message_from_bytes(raw)
    charsets = list(set(c.lower() for c in orig.get_charsets() if c))

    headers = {}
    meta = {'origin_uid': uid, 'files': [], 'errors': []}

    htm, files = parse_part(orig)
    if htm:
        embeds = {
            f['content-id']: '/raw/%s/%s' % (uid, f['path'])
            for f in files if 'content-id' in f
        }
        htm, extra_meta = html.clean(htm, embeds)
        meta.update(extra_meta)

    preview = htm and html.to_line(htm, 200)
    if len(preview) < 200 and files:
        preview += (' ' if preview else '') + (
            '[%s]' % ', '.join(f['filename'] for f in files)
        )
    meta['preview'] = preview
    meta['files'] = files

    for n in ('From', 'Sender', 'Reply-To', 'To', 'CC', 'BCC',):
        v = decode_header(orig[n], n)
        if v is None:
            continue
        headers[n] = v

    fields = (
        ('From', 1), ('Sender', 1),
        ('Reply-To', 0), ('To', 0), ('CC', 0), ('BCC', 0)
    )
    for n, one in fields:
        v = headers.get(n)
        if not v:
            continue
        v = addresses(v)
        meta[n.lower()] = v[0] if one else v

    subj = decode_header(orig['subject'], 'Subject')
    meta['subject'] = str(subj).strip() if subj else subj

    refs = orig['references']
    refs = refs.split() if refs else []
    if not refs:
        in_reply_to = orig['in-reply-to']
        refs = [in_reply_to] if in_reply_to else []
    meta['parent'] = refs[0] if refs else None
    refs = [r for r in refs if r in mids]

    mid = orig['message-id']
    if mid is None:
        log.info('## UID=%s has no "Message-Id" header', uid)
        mid = '<mailur@noid>'
    else:
        mid = mid.strip()
    meta['msgid'] = mid
    if mids[mid][0] != uid:
        log.info('## UID=%s duplicate: {%r: %r}', uid, mid, mids[mid])
        meta['duplicate'] = mid
        mid = gen_msgid('dup')

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    meta['arrived'] = int(arrived.timestamp())

    date = orig['date']
    meta['date'] = date and int(parsedate_to_datetime(date).timestamp())

    msg = MIMEPart(policy)
    msg.add_header('X-UID', '<%s>' % uid)
    msg.add_header('Message-Id', mid)
    msg.add_header('Subject', meta['subject'])
    msg.add_header('Date', orig['Date'])

    for n, v in headers.items():
        if not v:
            continue
        msg.add_header(n, v)

    if msg['from'] == 'mailur@link':
        msg.add_header('References', orig['references'])
    elif refs:
        msg.add_header('References', ' '.join(refs))

    msg.make_mixed()
    meta_txt = json.dumps(meta, sort_keys=True, ensure_ascii=False, indent=2)
    msg.attach(binary(meta_txt, 'application/json'))
    msg.attach(binary(htm))

    flags = []
    if meta['errors']:
        flags.append('#err')
    if meta.get('duplicate'):
        flags.append('#dup')
    return msg, flags


def gen_msgid(label):
    return '<%s@mailur.%s>' % (uuid.uuid4().hex, label)


def address_name(a):
    if a[0]:
        return a[0]
    try:
        index = a[1].index('@')
    except ValueError:
        return a[1]
    return a[1][:index]


def addresses(txt):
    addrs = [
        {
            'addr': a[1],
            'name': address_name(a),
            'title': '{} <{}>'.format(*a) if a[0] else a[1],
            'hash': hashlib.md5(a[1].strip().lower().encode()).hexdigest(),
        } for a in getaddresses([txt])
    ]
    return addrs