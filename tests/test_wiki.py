"""Wiki evidence and image ingestion behavior: no OCR assumptions, no real image text."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wiki_store', BASE/'scripts'/'wiki_store.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def event(key='shot-001', *, vendor='rice-house', name='老街米线', kind='store_screenshot',
          excerpt='店铺截图：老街米线，米线有番茄口味', obs=None, feedback=None):
    result = {
        'source': {'kind':kind,'origin':'用户手动上传图片','ref':'attachment://test/one',
                   'source_key':key,'excerpt':excerpt,'captured_at':'2026-11-05T13:00:00'},
        'entity': {'vendor_id':vendor,'name':name,'city':'上海', 'cuisine':'米线'},
        'observations':obs if obs is not None else [
            {'category':'product','value':'有番茄米线','certainty':'tentative','voice':'unknown'}]
    }
    if feedback is not None:
        result['personal_feedback'] = feedback
    return result


class _WikiFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        w.HOME = Path(self.tmp.name)
        w.WIKI = w.HOME/'wiki'
        w.SOURCES = w.WIKI/'sources'
        w.PAGES = w.WIKI/'pages'

    def tearDown(self):
        self.tmp.cleanup()



class WikiTest(_WikiFixture, unittest.TestCase):
    def test_store_screenshot_does_not_imply_visit_or_like(self):
        saved = w.ingest(event())
        self.assertEqual(saved['status'], 'saved')
        page = (w.PAGES/'rice-house.md').read_text(encoding='utf-8')
        self.assertIn('有番茄米线', page)
        self.assertIn('尚无本人确认', page)
        self.assertEqual(w.read_json(w.WIKI/'preferences.json'), [])

    def test_explicit_user_preference_and_visit(self):
        e = event(key='self-001',kind='text',excerpt='我昨天吃过，喜欢番茄汤底，不喜欢太辣',
                  obs=[{'category':'taste','value':'番茄汤底浓郁','certainty':'confirmed','voice':'user'}],
                  feedback={'explicit':True,'visit_status':'visited',
                            'preferences':[{'trait':'番茄汤底','polarity':'like'},
                                           {'trait':'太辣','polarity':'dislike'}]})
        saved=w.ingest(e)
        prefs=w.read_json(w.WIKI/'preferences.json')
        self.assertEqual(len(prefs),2)
        self.assertTrue(all(p['source_id']==saved['source_id'] for p in prefs))
        self.assertIn('visited', (w.PAGES/'rice-house.md').read_text(encoding='utf-8'))

    def test_third_party_recommendation_not_own_preference(self):
        e=event(key='review-01',kind='review_screenshot',excerpt='他人点评：这家很好吃',
                obs=[{'category':'taste','value':'评论说很美味','certainty':'tentative','voice':'third_party'}])
        w.ingest(e)
        self.assertEqual(w.read_json(w.WIKI/'preferences.json'), [])
        page=(w.PAGES/'rice-house.md').read_text(encoding='utf-8')
        self.assertIn('third_party',page)

    def test_unknown_store_stays_in_inbox(self):
        e=event(vendor=None,name='',kind='food_photo',excerpt='照片看起来像烤鱼；不知道店名')
        result=w.ingest(e)
        self.assertTrue(result['unassigned'])
        self.assertEqual(list(w.PAGES.glob('*.md')),[])
        self.assertEqual(w.read_json(w.WIKI/'index.json')['source_count'],1)

    def test_duplicate_source_is_idempotent_even_with_new_capture_time(self):
        e=event()
        a=w.ingest(e)
        e['source']['captured_at']='2026-11-06T19:00:00'
        b=w.ingest(e)
        self.assertEqual(a['source_id'],b['source_id'])
        self.assertEqual(b['status'],'duplicate')
        self.assertEqual(len(w.sources_all()),1)

    def test_same_source_conflicting_parse_rejected(self):
        w.ingest(event())
        e=event()
        e['observations'][0]['value']='有牛肉米线'
        with self.assertRaisesRegex(ValueError, '相同来源'):
            w.ingest(e)
        self.assertEqual(len(w.sources_all()),1)

    def test_conflicting_prices_retained_but_official_menu_unchanged(self):
        official=w.HOME/'vendors'/'rice-house'/'menu.json'
        w.write_json(official, {'items':[{'name':'番茄米线','price_cents':1800}]})
        w.ingest(event(key='price-one', excerpt='菜单截图：番茄米线18元',
                       obs=[{'category':'price','value':'番茄米线18元','certainty':'confirmed','voice':'unknown'}]))
        w.ingest(event(key='price-two', excerpt='群消息：番茄米线20元',
                       obs=[{'category':'price','value':'番茄米线20元','certainty':'tentative','voice':'third_party'}]))
        page=(w.PAGES/'rice-house.md').read_text(encoding='utf-8')
        self.assertIn('18元',page)
        self.assertIn('20元',page)
        self.assertEqual(w.read_json(official)['items'][0]['price_cents'],1800)

    def test_wiki_ingestion_cannot_change_orders(self):
        orders=w.HOME/'vendors'/'rice-house'/'orders.json'
        w.write_json(orders, {'last':{'confirmed_total':'10'}})
        before=orders.read_bytes()
        w.ingest(event())
        self.assertEqual(orders.read_bytes(),before)

    def test_inferred_visits_prohibited(self):
        e=event(feedback={'explicit':False,'visit_status':'visited'})
        with self.assertRaisesRegex(ValueError, '不能仅根据截图'):
            w.ingest(e)
        self.assertFalse(w.SOURCES.exists())

    def test_unsourced_preferences_prohibited(self):
        e=event(feedback={'explicit':False,'preferences':[{'trait':'好吃','polarity':'like'}]})
        with self.assertRaisesRegex(ValueError,'不能写入个人喜好'):
            w.ingest(e)

    def test_invalid_vendor_id_rejected(self):
        e=event(vendor='../attack')
        with self.assertRaisesRegex(ValueError,'kebab-case'):
            w.ingest(e)

    def test_search_cuisine_and_taste(self):
        w.ingest(event())
        self.assertEqual(w.search('番茄')['hits'][0]['vendor_id'],'rice-house')
        self.assertEqual(w.search('米线')['hits'][0]['name'],'老街米线')

    def test_preserve_manual_markdown_on_rebuild(self):
        w.PAGES.mkdir(parents=True)
        manual=w.PAGES/'my-notes.md'
        manual.write_text('# My own notes',encoding='utf-8')
        w.ingest(event())
        w.compile_wiki()
        self.assertEqual(manual.read_text(encoding='utf-8'),'# My own notes')

    def test_split_store_data_isolated(self):
        w.ingest(event())
        w.ingest(event(key='rice-alt',vendor='another-shop',name='隔壁面馆',
                       obs=[{'category':'product','value':'这家卖牛肉面','certainty':'confirmed','voice':'unknown'}]))
        p1=(w.PAGES/'rice-house.md').read_text(encoding='utf-8')
        p2=(w.PAGES/'another-shop.md').read_text(encoding='utf-8')
        self.assertNotIn('牛肉面',p1)
        self.assertNotIn('番茄米线',p2)

    def test_unrelated_sources_no_fabricated_vendor(self):
        e=event(key='food-unknown',vendor=None,name='',kind='food_photo',
                excerpt='只有菜品图片，没有定位没有店名')
        w.ingest(e)
        self.assertEqual(w.read_json(w.WIKI/'index.json')['vendors'], [])

if __name__=='__main__':
    unittest.main()

# Additional media-copy tests are registered by unittest discovery as a class.
class MediaIngestTest(_WikiFixture, unittest.TestCase):
    def test_media_file_copied_and_fingerprinted(self):
        image = w.HOME/'example.png'
        image.write_bytes(b'local-example-image-bytes')
        e = event(key='', excerpt='一张看得到店名的图片')
        result = w.ingest(e, media_file=str(image))
        src = w.read_json(w.SOURCES/(result['source_id']+'.json'))['source']
        self.assertTrue(src['ref'].startswith('media/'))
        self.assertTrue((w.WIKI/src['ref']).is_file())
        self.assertEqual((w.WIKI/src['ref']).read_bytes(),image.read_bytes())

    def test_media_file_invalid_extension_fails_closed(self):
        bad = w.HOME/'bad.sh'
        bad.write_text('echo no',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'仅支持'):
            w.ingest(event(), media_file=str(bad))
        self.assertFalse(w.SOURCES.exists())
