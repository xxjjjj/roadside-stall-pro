"""Tests for production-safe behavior beyond the original happy-path fixtures."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from types import SimpleNamespace

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / 'scripts' / 'stall_calc.py'
spec = importlib.util.spec_from_file_location('stall_calc_regression', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class RegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        mod.HOME = Path(self.tmp.name)
        self.menu = {'items':[{'name':'鸡蛋饼','price_cents':500,'aliases':['蛋饼']},
                              {'name':'馒头','price_cents':200}]}
        self.args = dict(vendor='stall-one', display_name='王姐饼摊', group=None, pricing='fixed',
                         sells=None, note=None, menu_json=json.dumps(self.menu, ensure_ascii=False),
                         ensure=False, city=None, address=None, confirm_fixed_price_change=False,
                         allow_remove_items=False)
        self.create(**self.args)

    def create(self, **kwargs):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return mod.cmd_new_vendor(SimpleNamespace(**kwargs))

    def cli(self, *params):
        env={**os.environ, 'ROADSIDE_STALL_HOME':self.tmp.name}
        return subprocess.run([sys.executable, str(SCRIPT), *params], text=True, capture_output=True, env=env)

    def test_zero_draft_never_overwrites_last(self):
        previous = mod.calculate({'orders':[{'item':'蛋饼','qty':2}]},self.menu)
        mod.save_last('stall-one',previous)
        with self.assertRaisesRegex(ValueError,'空订单'):
            mod.save_last('stall-one',mod.calculate({'orders':[]},self.menu))
        self.assertEqual(mod.last_rows('stall-one')[0]['qty'],2)
        self.assertEqual(len(mod.load_orders('stall-one')['log']),1)

    def test_pending_order_not_saved(self):
        before = mod.load_orders('stall-one')
        pending=mod.calculate({'orders':[{'item':'五花肉','qty':2}]},self.menu)
        with self.assertRaisesRegex(ValueError,'待确认'):
            mod.save_last('stall-one',pending)
        self.assertEqual(mod.load_orders('stall-one'),before)

    def test_save_draft_does_not_inflate_spend(self):
        payload=json.dumps({'orders':[{'item':'蛋饼','qty':2}]},ensure_ascii=False)
        done=self.cli('--vendor','stall-one','--json',payload,'--save')
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(mod.last_rows('stall-one')[0]['qty'],2)
        self.assertEqual(len(mod.load_orders('stall-one')['log']),0)
        self.assertIn('草稿',mod.render_last('stall-one'))
        done2=self.cli('--vendor','stall-one','--json',payload,'--confirm-order')
        self.assertEqual(done2.returncode,0,done2.stderr)
        self.assertEqual(len(mod.load_orders('stall-one')['log']),1)
        self.assertIn('¥10',mod.render_stats('stall-one'))

    def test_missing_base_last_is_error(self):
        result=self.cli('--vendor','stall-one','--base','last','--json','{"orders":[{"item":"蛋饼","qty":1}]}')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('找不到该摊位上一单',result.stderr)

    def test_fixed_change_needs_confirmation(self):
        alt={'items':[{'name':'鸡蛋饼','price_cents':600,'aliases':['蛋饼']}, {'name':'馒头','price_cents':200}]}
        cmd=['--vendor','stall-one','--update-menu','--menu-json',json.dumps(alt,ensure_ascii=False)]
        failed=self.cli(*cmd)
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(mod.load_menu('stall-one')['items'][0]['price_cents'],500)
        okay=self.cli(*cmd,'--confirm-fixed-price-change')
        self.assertEqual(okay.returncode,0,okay.stderr)
        self.assertEqual(mod.load_menu('stall-one')['items'][0]['price_cents'],600)

    def test_partial_update_cannot_remove_items_silently(self):
        short={'items':[{'name':'鸡蛋饼','price_cents':500,'aliases':['蛋饼']}]}
        cmd=['--vendor','stall-one','--update-menu','--menu-json',json.dumps(short,ensure_ascii=False)]
        failed=self.cli(*cmd)
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(len(mod.load_menu('stall-one')['items']),2)
        okay=self.cli(*cmd,'--allow-remove-items','--confirm-fixed-price-change')
        self.assertEqual(okay.returncode,0,okay.stderr)
        self.assertEqual(len(mod.load_menu('stall-one')['items']),1)

    def test_rename_only_does_not_need_pricing(self):
        a={**self.args, 'ensure':True, 'pricing':None, 'display_name':'王姐新店名', 'menu_json':None}
        self.create(**a)
        self.assertEqual(mod.load_profile('stall-one')['name'],'王姐新店名')
        self.assertEqual(mod.load_profile('stall-one')['pricing'],'fixed')

    def test_invalid_menu_does_not_leave_partial_vendor(self):
        a={**self.args, 'vendor':'invalid-stall', 'menu_json':json.dumps({'items':[{'name':'蛋饼','price_cents':0}]},ensure_ascii=False)}
        with self.assertRaises(SystemExit):self.create(**a)
        self.assertFalse((mod.vendor_dir('invalid-stall')/'profile.json').exists())

    def test_reject_mixed_vendor_lines(self):
        payload={'_vendor':'stall-one','orders':[{'person':'甲','item':'蛋饼','qty':2,'shop':'stall-two'},
                                                {'person':'乙','item':'蛋饼','qty':1}]}
        out=mod.calculate(payload,self.menu)
        self.assertEqual(out['confirmed_total'],'5')
        self.assertEqual(len(out['pending']),1)
        self.assertIn('另一家店',out['pending'][0]['reason'])

    def test_corrupt_records_must_not_be_ignored(self):
        path=mod.vendor_dir('stall-one')/'orders.json'
        path.write_text('{not-json',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'文件损坏'):
            mod.load_orders('stall-one')
        self.assertEqual(path.read_text(encoding='utf-8'),'{not-json')

    def test_duplicate_names_rejected(self):
        bad={'items':[{'name':'饼','price_cents':100},{'name':' 饼 ','price_cents':200}]}
        with self.assertRaises(SystemExit):mod.validate_menu(bad)

    def test_reject_path_like_vendor_id(self):
        with self.assertRaises(SystemExit):mod.vendor_dir('..\\outside')
        with self.assertRaises(SystemExit):mod.vendor_dir('abc..xyz')

    def test_city_filter(self):
        a={**self.args,'vendor':'shanghai-shop','city':'上海','menu_json':None,'pricing':'none'}
        self.create(**a)
        self.assertEqual([x['id'] for x in mod.cmd_search('王姐',city='上海')], ['shanghai-shop'])

    def test_import_20_item_menu(self):
        real=json.loads((BASE/'references'/'kun-ge-bbq-menu.json').read_text(encoding='utf-8'))
        mod.validate_menu(real)
        a={**self.args,'vendor':'kun-ge-bbq','pricing':'fixed','menu_json':json.dumps(real,ensure_ascii=False)}
        self.create(**a)
        out=mod.calculate({'_vendor':'kun-ge-bbq','orders':[{'person':'晶晶','item':'羊肉','qty':10},
           {'person':'晶晶','item':'牛肉','qty':5},{'person':'小刘','item':'鸡皮','qty':3},
           {'person':'小刘','item':'面筋','qty':2},{'person':'小刘','item':'小饼','qty':1},
           {'person':'小刘','item':'鸡皮','qty':5,'action':'set'}]},real)
        self.assertEqual(out['confirmed_total'],'47')
        self.assertEqual(len(real['items']),20)
        self.assertEqual([x['subtotal'] for x in out['people']], ['30','17'])

if __name__ == '__main__':unittest.main()
