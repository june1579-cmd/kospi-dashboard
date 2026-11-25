// 2026-11-25 추가: 모든 웹판 최상단에 웹판 바로가기 줄(코스피·선물옵션·연구소·방어종목 명단·AI 경고판)을 붙인다.
// 각 웹판 index.html 의 <head> 에서 defer 로 읽는다. 대시보드 페이지(page.html = 아티팩트 files/index.html)에도 같은 줄(.webnav-page)이 글로 들어 있어
// 웹판에서는 이 파일이 만든 줄만 보이게 페이지 쪽 줄을 숨긴다(html.has-webnav). 다른 코드와 변수를 나누지 않는다.
(function () {
  if (document.getElementById('webnav')) return;
  var BASE = 'https://june1579-cmd.github.io/kospi-dashboard/';
  var LINKS = [['', '코스피 대시보드'], ['fo/', '선물옵션'], ['lab/', '연구소'], ['stocks/', '방어종목 명단'], ['ai/', 'AI 경고판']];
  var css = '.webnav{display:flex;align-items:center;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;padding:8px 12px;margin:0;'
    + 'background:#1b1f24;font:600 13px/1.3 -apple-system,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;position:relative;z-index:50}'
    + '.webnav::-webkit-scrollbar{display:none}'
    + '.webnav .wn-l{color:#9aa3ad;font-weight:500;font-size:12px;flex:none;margin-right:2px}'
    + '.webnav a{flex:none;color:#e6e8eb;text-decoration:none;border:1px solid #3a414b;border-radius:999px;padding:4px 11px;white-space:nowrap}'
    + '.webnav a:hover{border-color:#8a93a0}'
    + '.webnav a:not([aria-current])::after{content:"\\2197";margin-left:4px;font-size:11px;opacity:.75}'
    + '.webnav a[aria-current="page"]{background:#e6e8eb;color:#1b1f24;border-color:#e6e8eb}'
    + 'html.has-webnav .webnav-page{display:none!important}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  var path = location.pathname.replace(/index\.html$/, '');
  var cur = '';
  LINKS.forEach(function (l) { if (l[0] && path.indexOf('/' + l[0]) !== -1) cur = l[0]; });
  var nav = document.createElement('nav'); nav.id = 'webnav'; nav.className = 'webnav'; nav.setAttribute('aria-label', '웹판 바로가기');
  var lab = document.createElement('span'); lab.className = 'wn-l'; lab.textContent = '웹판'; nav.appendChild(lab);
  LINKS.forEach(function (l) {
    var a = document.createElement('a'); a.href = BASE + l[0]; a.textContent = l[1]; a.title = l[1] + ' 웹판 열기 — ' + BASE + l[0];
    if (l[0] === cur) a.setAttribute('aria-current', 'page');
    nav.appendChild(a);
  });
  document.documentElement.classList.add('has-webnav');
  document.body.insertBefore(nav, document.body.firstChild);
})();
