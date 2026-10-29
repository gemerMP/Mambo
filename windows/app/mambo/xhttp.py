"""Validate the supported XHTTP share-link options without accepting file paths."""
import json
import re
from .core import MamboError

def settings(q):
    try:
        extra=json.loads(q.get('extra') or '{}')
        if not isinstance(extra,dict) or set(extra)-{'mode','xPaddingBytes','noGRPCHeader','noSSEHeader'}:
            raise ValueError()
        mode=q.get('mode') or extra.pop('mode','auto')
        if mode not in ('auto','packet-up','stream-up','stream-one'):raise ValueError()
        padding=q.get('x_padding_bytes') or extra.get('xPaddingBytes')
        if padding is not None:
            if not isinstance(padding,(str,int)) or not re.fullmatch(r'\d{1,6}(?:-\d{1,6})?',str(padding)):raise ValueError()
            extra['xPaddingBytes']=str(padding)
        for key in ('noGRPCHeader','noSSEHeader'):
            if key in extra and not isinstance(extra[key],bool):raise ValueError()
        return {'host':q.get('host') or '', 'path':q.get('path') or '/', 'mode':mode,'extra':extra}
    except (ValueError,TypeError):
        raise MamboError('Параметры XHTTP не поддерживаются: допустимы mode, xPaddingBytes, noGRPCHeader, noSSEHeader.')
