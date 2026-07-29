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

const SHELL_CACHE = 'gyeotnun-shell-v1'
const SHARE_CACHE = 'gyeotnun-share-v1'
const SHARE_KEY = '/__shared-image'
const SHELL_FILES = ['/', '/manifest.json', '/icon-192.png', '/icon-512.png']

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

  // ── 앱 셸만 캐시 우선(설치 요건 충족용 최소 오프라인) ──
  if (req.method === 'GET' && SHELL_FILES.includes(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req))
    )
  }
})
