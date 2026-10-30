"""Run the native observer's actual embedded Python against controlled HTTPS replies."""
import io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_gateway import TEXT

CODE=TEXT.split("<<'PY_CORIUM_PUBLIC_ADDRESS'\n",1)[1].split('\nPY_CORIUM_PUBLIC_ADDRESS',1)[0]

class NativeAddressTests(unittest.TestCase):
    def test_cache_expires_and_adapts_then_offline_discards_stale_ip(self):
        with tempfile.TemporaryDirectory() as directory,patch('sys.argv',['observer',directory,'auto','54.64.24.133']),patch('urllib.request.build_opener') as create:
            create.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(b'13.112.54.178\n')
            with patch('sys.stdout',new_callable=io.StringIO) as out:exec(CODE,{'__name__':'__main__'})
            self.assertEqual(out.getvalue().strip(),'13.112.54.178')
            with patch('sys.stdout',new_callable=io.StringIO) as out:
                with self.assertRaises(SystemExit):exec(CODE,{'__name__':'__main__'})
            self.assertEqual(create.return_value.open.call_count,1)
            p=Path(directory)/'public-address.json';value=json.loads(p.read_text());value['observed_at']-=301;value['attempted_at']-=301;p.write_text(json.dumps(value))
            create.return_value.open.side_effect=lambda *a,**kw:io.BytesIO(b'8.8.8.8')
            with patch('sys.stdout',new_callable=io.StringIO) as out:exec(CODE,{'__name__':'__main__'})
            self.assertEqual(out.getvalue().strip(),'8.8.8.8')
            value=json.loads(p.read_text());value['observed_at']-=301;value['attempted_at']-=301;p.write_text(json.dumps(value));create.return_value.open.side_effect=OSError('offline')
            with self.assertRaises(SystemExit):exec(CODE,{'__name__':'__main__'})
            self.assertNotIn('address',json.loads(p.read_text()))
