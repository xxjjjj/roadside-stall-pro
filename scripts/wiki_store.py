#!/usr/bin/env python3
"""Evidence-first personal food wiki for 路边摊 Pro.

The vision/LLM layer proposes structured evidence. This deterministic layer
stores immutable sources, recompiles grounded vendor pages/preferences, and
never changes menus or orders. Standard library only, no network calls.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

HOME = Path(os.environ.get('ROADSIDE_STALL_HOME') or str(Path.home() / '.roadside-stall'))
WIKI = HOME / 'wiki'
SOURCES = WIKI / 'sources'
PAGES = WIKI / 'pages'

KINDS = {'wechat_screenshot', 'chat_screenshot', 'store_screenshot', 'menu_photo',
         'food_photo', 'map_screenshot', 'review_screenshot', 'text', 'other'}
CATEGORIES = {'menu', 'price', 'taste', 'environment', 'service', 'location',
              'opening_hours', 'product', 'contact', 'other'}
CERTAINTIES = {'confirmed', 'tentative'}
VOICES = {'user', 'third_party', 'unknown'}
STATUSES = {'visited', 'want_to_try', 'not_visited', 'unknown'}
POLARITIES = {'like', 'dislike'}


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ValueError(f'知识库文件损坏，已停止操作：{path}: {exc}') from exc


def require_str(value, field, limit=2000, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f'{field} 必须为非空字符串')
    if len(value) > limit:
        raise ValueError(f'{field} 超出长度上限 {limit}')
    return value.strip()


def clean_vendor_id(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', value) or len(value) > 64:
        raise ValueError('vendor_id 必须为小写 kebab-case 字符串且不能包含路径字符')
    return value


def parse_record(obj):
    if not isinstance(obj, dict):
        raise ValueError('知识摄入必须是 JSON 对象')
    src = obj.get('source')
    if not isinstance(src, dict):
        raise ValueError('必须提供 source 对象')
    kind = src.get('kind')
    if kind not in KINDS:
        raise ValueError('source.kind 不支持：' + str(kind))
    # A source needs traceable evidence, not fabricated appearance or assertions.
    origin = require_str(src.get('origin', ''), 'source.origin', 300)
    excerpt = require_str(src.get('excerpt', ''), 'source.excerpt', 12000, allow_empty=True)
    ref = require_str(src.get('ref', ''), 'source.ref', 1000, allow_empty=True)
    if not excerpt and not ref:
        raise ValueError('必须有 source.excerpt 或 source.ref 才能回溯证据')
    source_key = src.get('source_key', '')
    if source_key:
        source_key = require_str(source_key, 'source.source_key', 300)
    captured_at = require_str(src.get('captured_at', datetime.now().isoformat(timespec='seconds')), 'source.captured_at', 80)
    entity = obj.get('entity') or {}
    if not isinstance(entity, dict):
        raise ValueError('entity 必须是对象')
    vendor_id = clean_vendor_id(entity.get('vendor_id'))
    name = entity.get('name', '')
    if name:
        name = require_str(name, 'entity.name', 150)
    if vendor_id and not name:
        raise ValueError('提供 vendor_id 时必须有明确的店名，不得仅凭编号臆测')
    meta = {}
    for field in ('city', 'address', 'cuisine', 'group', 'category'):
        val = entity.get(field, '')
        meta[field] = require_str(val, f'entity.{field}', 400, allow_empty=True)
    observations = obj.get('observations', [])
    if not isinstance(observations, list) or len(observations) > 100:
        raise ValueError('observations 必须是长度不超过100的数组')
    cleaned_observations = []
    for i, item in enumerate(observations):
        if not isinstance(item, dict) or item.get('category') not in CATEGORIES:
            raise ValueError(f'observations[{i}].category 不合法')
        value = require_str(item.get('value', ''), f'observations[{i}].value', 1000)
        certainty = item.get('certainty', 'tentative')
        if certainty not in CERTAINTIES:
            raise ValueError('certainty 只能 confirmed/tentative')
        voice = item.get('voice', 'unknown')
        if voice not in VOICES:
            raise ValueError('voice 只能 user/third_party/unknown')
        # Keep outside attribution attached; another reviewer's praise isn't user's taste.
        cleaned_observations.append({'category': item['category'], 'value': value,
                                     'certainty': certainty, 'voice': voice})
    feedback = obj.get('personal_feedback') or {}
    if not isinstance(feedback, dict):
        raise ValueError('personal_feedback 必须是对象')
    visit_status = feedback.get('visit_status', 'unknown')
    if visit_status not in STATUSES:
        raise ValueError('personal_feedback.visit_status 无效')
    explicit = feedback.get('explicit', False)
    if not isinstance(explicit, bool):
        raise ValueError('personal_feedback.explicit 必须是布尔值')
    if not explicit and visit_status != 'unknown':
        raise ValueError('不能仅根据截图推断用户去过、没去过或想去；必须提供 explicit=true 与用户原话')
    prefs = feedback.get('preferences', [])
    if not isinstance(prefs, list) or len(prefs) > 50:
        raise ValueError('personal_feedback.preferences 必须是不超过50项的数组')
    clean_prefs = []
    for idx, p in enumerate(prefs):
        if not isinstance(p, dict) or p.get('polarity') not in POLARITIES:
            raise ValueError(f'preferences[{idx}].polarity 必须为 like/dislike')
        if not explicit:
            raise ValueError('没有明确用户表达时，不能写入个人喜好')
        clean_prefs.append({'trait': require_str(p.get('trait', ''), 'preference.trait', 150),
                            'polarity': p['polarity']})
    if explicit and (visit_status != 'unknown' or prefs) and not excerpt:
        raise ValueError('写个人喜好/到访状态必须保存用户原话作为 source.excerpt')
    if vendor_id is None and observations:
        # Still useful as inbox evidence, but it must not materialize a phantom vendor.
        pass
    rec = {'source': {'kind': kind, 'origin': origin, 'excerpt': excerpt,
                      'ref': ref, 'source_key': source_key, 'captured_at': captured_at},
           'entity': {'vendor_id': vendor_id, 'name': name, **meta},
           'observations': cleaned_observations,
           'personal_feedback': {'visit_status': visit_status, 'explicit': explicit,
                                 'preferences': clean_prefs}}
    return rec


def source_id_for(rec):
    src = rec['source']
    if src.get('source_key'):
        identity = src['origin'] + '\n' + src['source_key']
    else:
        # Normalize stable visible evidence; captured_at is not part of identity.
        identity = src['origin'] + '\n' + src['kind'] + '\n' + src['ref'] + '\n' + src['excerpt']
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


def sources_all():
    if not SOURCES.exists():
        return []
    result = []
    for p in sorted(SOURCES.glob('*.json')):
        rec = read_json(p)
        if not isinstance(rec, dict) or rec.get('source_id') != p.stem:
            raise ValueError('知识库来源记录结构异常：' + str(p))
        result.append(rec)
    return result


def prepare_media(media_file):
    """Compute a stable local evidence reference without relying on filename."""
    p = Path(media_file).expanduser().resolve()
    if not p.is_file():
        raise ValueError('图片文件不存在：' + str(p))
    if p.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.heic','.gif'):
        raise ValueError('当前仅支持 PNG/JPG/WEBP/HEIC/GIF 图片附件')
    if p.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('图片文件超过20MB，不自动导入')
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    rel = 'media/' + digest + p.suffix.lower()
    return p, digest, rel


def ingest(obj, media_file=None):
    rec = parse_record(obj)
    media = prepare_media(media_file) if media_file else None
    if media:
        _, digest, rel = media
        rec['source']['ref'] = rel
        if not rec['source']['source_key']:
            rec['source']['source_key'] = digest
    source_id = source_id_for(rec)
    dest = SOURCES / (source_id + '.json')
    if dest.exists():
        old = read_json(dest)
        # Same source must not be silently overwritten. Distinct interpretations
        # require an explicit new source_key revision.
        old_source = {k:v for k,v in old.get('source', {}).items() if k != 'captured_at'}
        new_source = {k:v for k,v in rec['source'].items() if k != 'captured_at'}
        if old_source != new_source or old.get('entity') != rec['entity'] or old.get('observations') != rec['observations'] or old.get('personal_feedback') != rec['personal_feedback']:
            raise ValueError('已存在相同来源但解析内容不同；请审查后通过新的 source_key 追加修订证据，不能静默覆盖')
        return {'status': 'duplicate', 'source_id': source_id, 'wiki_home': str(WIKI)}
    if media:
        src, _, rel = media
        target = WIKI / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(src, target)
    rec['source_id'] = source_id
    rec['ingested_at'] = datetime.now().isoformat(timespec='seconds')
    write_json(dest, rec)
    compile_wiki()
    return {'status': 'saved', 'source_id': source_id,
            'vendor_id': rec['entity']['vendor_id'],
            'wiki_home': str(WIKI),
            'unassigned': not bool(rec['entity']['vendor_id'])}


def grouped():
    vendors = {}
    prefs = []
    inbox = []
    for r in sources_all():
        vid = r['entity'].get('vendor_id')
        if vid:
            vendors.setdefault(vid, []).append(r)
        else:
            inbox.append(r['source_id'])
        fb = r['personal_feedback']
        if fb.get('explicit'):
            for p in fb.get('preferences', []):
                prefs.append({'vendor_id': vid, 'vendor_name': r['entity'].get('name', ''),
                              'trait': p['trait'], 'polarity': p['polarity'],
                              'source_id': r['source_id']})
    return vendors, prefs, inbox


def vendor_page(vid, evidence):
    entity = evidence[-1]['entity']
    names = [r['entity'].get('name') for r in evidence if r['entity'].get('name')]
    name = names[-1] if names else vid
    lines = ['<!-- GENERATED BY roadside-stall-pro/wiki_store.py; DO NOT EDIT -->', '', f'# {name}', '', f'- 商家标识：`{vid}`']
    for key, label in [('city','城市'), ('address','位置'), ('cuisine','菜系'), ('group','信息来源群'),('category','类型')]:
        values = [(r['entity'].get(key), r['source_id']) for r in evidence if r['entity'].get(key)]
        if values:
            val, sid = values[-1]
            lines.append(f'- {label}：{val}（来源 `{sid}`）')
    lines += ['', '## 证据笔记（不等于全部已核实）']
    if not any(r['observations'] for r in evidence):
        lines.append('- 暂无菜品或体验描述')
    for r in evidence:
        for o in r['observations']:
            label = '待核实' if o['certainty']=='tentative' else '已确认记录'
            lines.append(f"- [{label}][{o['category']}][{o['voice']}] {o['value']}（来源 `{r['source_id']}`）")
    lines += ['', '## 我的到访与口味（仅用户明确表达）']
    found = False
    for r in evidence:
        fb = r['personal_feedback']
        if fb['explicit'] and (fb['visit_status']!='unknown' or fb['preferences']):
            found = True
            if fb['visit_status'] != 'unknown':
                lines.append(f"- 到访/意向：{fb['visit_status']}（来源 `{r['source_id']}`）")
            for p in fb['preferences']:
                lines.append(f"- {('喜欢' if p['polarity']=='like' else '不喜欢')}：{p['trait']}（来源 `{r['source_id']}`）")
    if not found:
        lines.append('- 尚无本人确认的到访或喜好记录；保存截图不等于去过/喜欢')
    lines += ['', '## 原始来源']
    for r in evidence:
        s = r['source']
        lines.append(f"- `{r['source_id']}`：{s['kind']} · {s['origin']} · {s['captured_at']} · {s['ref'] or '文字记录'}")
    return '\n'.join(lines) + '\n'


def compile_wiki():
    vendors, preferences, inbox = grouped()
    PAGES.mkdir(parents=True, exist_ok=True)
    for vid, evidence in vendors.items():
        p = PAGES / (vid + '.md')
        content = vendor_page(vid, evidence)
        tmp = p.with_suffix('.md.tmp')
        tmp.write_text(content, encoding='utf-8')
        tmp.replace(p)
    # Only clean generated pages; preserve any manual notes stored alongside them.
    for p in PAGES.glob('*.md'):
        if p.stem not in vendors and p.read_text(encoding='utf-8').startswith('<!-- GENERATED BY roadside-stall-pro/wiki_store.py; DO NOT EDIT -->'):
            p.unlink()
    write_json(WIKI / 'preferences.json', preferences)
    write_json(WIKI / 'index.json', {'vendors': sorted(vendors), 'unassigned_sources': inbox,
                                      'source_count': sum(len(v) for v in vendors.values())+len(inbox)})
    return {'vendors': len(vendors), 'unassigned': len(inbox), 'preferences': len(preferences)}


def search(term):
    if not term.strip():
        raise ValueError('搜索词不能为空')
    t = ''.join(term.lower().split())
    vendors, _, inbox = grouped()
    hits = []
    for vid, evidence in vendors.items():
        hay = [vid]
        for r in evidence:
            hay.extend([r['entity'].get(x, '') for x in ('name','city','address','cuisine','category','group')])
            hay.extend([o['value'] for o in r['observations']])
            hay.extend([p['trait'] for p in r['personal_feedback']['preferences']])
        if t in ''.join(''.join(v.lower().split()) for v in hay):
            hits.append({'vendor_id': vid, 'name': evidence[-1]['entity']['name'],
                         'sources': [r['source_id'] for r in evidence],
                         'page': str(PAGES/(vid+'.md'))})
    return {'hits': hits, 'unassigned_count': len(inbox)}


def main():
    ap = argparse.ArgumentParser(description='路边摊 Pro · 基于来源证据的个人吃喝 Wiki')
    action=ap.add_mutually_exclusive_group(required=True)
    action.add_argument('--ingest-json', help='已从文字/图片提取的结构化 JSON 证据')
    action.add_argument('--ingest-file', help='上面 JSON 的 UTF-8 文件路径')
    action.add_argument('--rebuild', action='store_true', help='从原始证据重新编译全部知识页')
    action.add_argument('--find', help='查询商家/菜品/口味关键词')
    action.add_argument('--vendor', help='查看一个商家 Wiki 页面（vendor_id）')
    action.add_argument('--preferences', action='store_true', help='查看本人明确记录的偏好')
    action.add_argument('--list', action='store_true', help='查看 Wiki 概览')
    action.add_argument('--source', help='查看某条来源证据 source_id')
    ap.add_argument('--media-file', help='附带本地图片文件并复制到 Wiki 证据目录（仅与摄入参数同时使用）')
    args=ap.parse_args()
    if args.media_file and not (args.ingest_json or args.ingest_file):
        ap.error('--media-file 仅用于 --ingest-json 或 --ingest-file')
    try:
        if args.ingest_json or args.ingest_file:
            data=json.loads(Path(args.ingest_file).read_text(encoding='utf-8')) if args.ingest_file else json.loads(args.ingest_json)
            print(json.dumps(ingest(data, media_file=args.media_file),ensure_ascii=False,indent=2))
        elif args.rebuild:
            print(json.dumps(compile_wiki(),ensure_ascii=False,indent=2))
        elif args.find:
            print(json.dumps(search(args.find),ensure_ascii=False,indent=2))
        elif args.vendor:
            vid=clean_vendor_id(args.vendor)
            p=PAGES/(vid+'.md')
            print(p.read_text(encoding='utf-8') if p.is_file() else '没有这家店的 Wiki 记录')
        elif args.preferences:
            print(json.dumps(read_json(WIKI/'preferences.json', []),ensure_ascii=False,indent=2))
        elif args.list:
            print(json.dumps(read_json(WIKI/'index.json', {'vendors': [],'unassigned_sources':[],'source_count':0}),ensure_ascii=False,indent=2))
        else:
            if not re.fullmatch(r'[0-9a-f]{24}',args.source):
                raise ValueError('source_id 格式不合法')
            print(json.dumps(read_json(SOURCES/(args.source+'.json'), {'error':'找不到这个来源'}),ensure_ascii=False,indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print('Wiki 操作失败：'+str(exc),file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
