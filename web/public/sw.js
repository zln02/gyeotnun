/**
 * 곁눈(Gyeotnun) 서비스 워커
 * 담당: 조희진
 *
 * 두 가지 일만 한다. 오프라인 완전 지원이 목적이 아니라 PWA 설치 요건
 * 충족 + Web Share Target 수신이 목적이라 캐싱은 최소한으로 둔다.
 *
 *  1) 앱 셸(정적 파일 몇 개)만 캐시해 설치 조건을 만족시킨다.
 *     API 응답(/api/*)은 절대 캐시하지 않는다 - 근거 대조·질문 생성처럼
 *     매번 실제 서버 응답이어야 하는 데이터를 오프라인 캐시로 돌려주면
 *     "판정하지 않는다"는 서비스 원칙이 낡은 데이터로 조용히 깨질 수 있다.
 *  2) Web Share Target(POST /share)을 가로채 공유된 이미지를 캐시에 담고
 *     S1 화면으로 리다이렉트한다. Home.jsx 가 이어서 꺼내 쓴다.
 */

// ★ v1→v2(2026-08): '/' 를 cache-first 로 캐싱했더니, 배포로 index.html 이
//   가리키는 JS/CSS 해시 파일명이 바뀌면 재방문자는 서비스워커가 물고 있는
//   "옛 index.html"(옛 해시를 가리킴)을 계속 받았다. 그 옛 해시 파일은 서버에
//   이미 없는데, nginx 의 SPA 폴백(try_files $uri /index.html)이 존재하지
//   않는 자산 요청에도 200 으로 index.html 을 되돌려주는 바람에(deploy/nginx
//   참고 - 별도로 /assets/ 를 404 처리하도록 고쳤다) 브라우저가 HTML 을
//   JS 로 파싱하려다 조용히 죽어 화면이 아예 안 뜨는 사고로 이어졌다.
//   버전 문자열을 올리면 activate 단계에서 구버전 캐시가 자동 삭제된다.
// v3: 앱 아이콘을 새 로고(logo-*.png)로 교체하면서 올렸다. 이 값을 올리지 않으면
//     activate 단계의 구버전 캐시 삭제가 돌지 않아 옛 파란 눈 아이콘이 계속 남는다.
const SHELL_CACHE = 'gyeotnun-shell-v3'
const SHARE_CACHE = 'gyeotnun-share-v1'
const SHARE_KEY = '/__shared-image'
// '/' 는 더 이상 여기 넣지 않는다 - 아래 fetch 핸들러에서 네트워크 우선으로
// 따로 처리한다(항상 최신 index.html 을 받고, 오프라인일 때만 캐시로 대체).
const SHELL_FILES = ['/manifest.json', '/logo-favicon.png', '/logo-192.png', '/logo-512.png']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_FILES))
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== SHARE_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  const url = new URL(req.url)

  // ── Web Share Target: 카카오톡 등에서 '공유 → 곁눈'으로 들어온 이미지 ──
  if (req.method === 'POST' && url.pathname === '/share') {
    event.respondWith(
      (async () => {
        try {
          const formData = await req.formData()
          const file = formData.get('image')
          if (file) {
            const cache = await caches.open(SHARE_CACHE)
            await cache.put(SHARE_KEY, new Response(file, { headers: { 'Content-Type': file.type || 'image/jpeg' } }))
          }
        } catch (e) {
          // 공유 데이터를 못 읽어도 흐름은 계속돼야 한다 - 홈 화면에서
          // '사진 올리기' 버튼으로 다시 시도할 수 있다.
        }
        return Response.redirect('/?share=1', 303)
      })()
    )
    return
  }

  // ── API 호출은 항상 네트워크로 - 캐시하지 않는다 ──
  if (url.pathname.startsWith('/api/') || url.pathname === '/health') {
    return
  }

  // ── 페이지 진입(navigation) 은 네트워크 우선 - 항상 최신 index.html 을
  //    받아야 새 배포의 새 자산 해시를 정확히 가리킨다. 오프라인일 때만
  //    직전에 성공했던 응답으로 대체한다(설치 요건용 최소 폴백).
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(SHELL_CACHE).then((cache) => cache.put(req, copy))
          return res
        })
        .catch(() => caches.match(req))
    )
    return
  }

  // ── 아이콘·매니페스트만 캐시 우선(설치 요건 충족용 최소 오프라인) ──
  if (req.method === 'GET' && SHELL_FILES.includes(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req))
    )
  }
})
