"""Display-only formatting of a verified native verdict; grants no permission."""
from datetime import datetime
from math import isfinite, ceil
from time import time


def presentation(value, now=None):
    now = time() if now is None else now
    state = value.get('state', 'invalid')
    kind, expiry = value.get('kind'), value.get('expiresAt')
    valid_end = isinstance(expiry, (int, float)) and not isinstance(expiry, bool) and isfinite(expiry)
    notice = value.get('message', '')
    if state == 'active':
        if kind == 'limited' and valid_end:
            if now >= expiry:
                state = 'expired'
                notice = '授权已过期。'
        elif kind != 'permanent' or expiry is not None:
            state = 'invalid'
            notice = '授权信息不完整，请重新验证。'
    title = {'active': 'VIP', 'expired': '已过期', 'revoked': '已注销'}.get(state, '未激活')
    source = '彩字单产品授权' if value.get('source') == 'color-product' else '—'
    term = {'permanent': '永久', 'limited': '限期'}.get(kind, '—')
    end, remaining = '—', '—'
    if kind == 'permanent' and expiry is None and state == 'active':
        end = remaining = '永久'
    elif valid_end:
        try:
            end = datetime.fromtimestamp(expiry).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        except (OverflowError, OSError, ValueError):
            end = f'UTC Unix {expiry}'
        if state == 'expired' or now >= expiry:
            remaining = '已过期'
        elif state == 'active':
            seconds = max(1, ceil(expiry - now))
            days, seconds = divmod(seconds, 86400)
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            remaining = (f'{days}天 ' if days else '') + f'{hours:02d}小时 {minutes:02d}分 {seconds:02d}秒'
    return dict(state=state, title=title, source=source, term=term, end=end,
                remaining=remaining, notice=notice, gold=state == 'active')
