import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 곁눈 프론트 개발 서버 설정 (담당: 조희진)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,          // 같은 와이파이의 실제 폰으로 접속해 테스트 (시니어 UX 검증 필수)
    proxy: {
      // /api 요청을 로컬 FastAPI 로 넘긴다. 백엔드가 꺼져 있어도
      // api.js 의 mock 모드가 켜져 있으면 화면은 계속 동작한다.
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
