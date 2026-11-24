# us-walls 실패 알림에 붙일 원인 한 줄(쉘에 안전한 글자만) — uswalls/latest.json 의 첫 오류
import json, re
try:
    e = (json.load(open('uswalls/latest.json', encoding='utf-8')).get('errors') or [''])[0]
except Exception:
    e = ''
print(re.sub(r'[\"\'`$\\]', '', e.replace('RuntimeError(', '').replace('\n', ' '))[:100])
