/**
 * 업로드 전 사진 줄이기
 * 담당: 조희진
 *
 * ★ 왜 넣었나 (2026-08 실측)
 *   휴대폰 갤러리에서 고른 사진은 3~12MB 다. 그걸 그대로 올리다 보니
 *   모바일 업링크에서 몇 초가 그냥 날아갔다(사진 탭 → 첫 질문까지 약 12.6초
 *   중 업로드 구간이 측정 밖에서 가장 크게 흔들리는 부분이었다).
 *
 * ★ 화질을 왜 깎아도 되나
 *   OCR 은 Claude Vision 이 하는데, 실측상 인식 시간이 이미지 크기에
 *   거의 영향을 받지 않았다(640×350 에서 3.35초, 900×968 에서 3.67초 -
 *   docs/evaluation/ocr_comparison.md). 즉 크게 올린다고 더 잘 읽지 않는다.
 *   긴 변 1280px 이면 문자 스크린샷 글자는 충분히 또렷하다.
 *
 * ★ 실패하면 절대 막지 않는다
 *   캔버스/비트맵 API 가 없거나 어떤 이유로든 변환이 실패하면 원본 파일을
 *   그대로 돌려준다. 사진 확인은 곁눈의 주 기능이라 여기서 멈추면 안 된다.
 */

const MAX_EDGE = 1280
const QUALITY = 0.85

/** 이 브라우저에서 캔버스 변환이 가능한지 */
function canResize() {
  return typeof document !== 'undefined'
    && typeof HTMLCanvasElement !== 'undefined'
    && typeof HTMLCanvasElement.prototype.toBlob === 'function'
}

/** File → ImageBitmap (구형 사파리 대비 <img> 폴백 포함) */
async function decode(file) {
  if (typeof createImageBitmap === 'function') {
    try { return await createImageBitmap(file) } catch { /* 아래 폴백으로 */ }
  }
  const url = URL.createObjectURL(file)
  try {
    return await new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('decode failed'))
      img.src = url
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * 사진을 긴 변 기준 maxEdge 이하로 줄인 File 을 돌려준다.
 * 이미 충분히 작거나 변환할 수 없으면 원본을 그대로 돌려준다.
 */
export async function downscaleImage(file, maxEdge = MAX_EDGE) {
  if (!file || !file.type?.startsWith('image/')) return file
  // GIF 는 애니메이션이 날아가고, SVG 는 래스터화하면 오히려 손해다.
  if (file.type === 'image/gif' || file.type === 'image/svg+xml') return file
  if (!canResize()) return file

  try {
    const src = await decode(file)
    const w = src.width
    const h = src.height
    if (!w || !h) return file
    const longest = Math.max(w, h)
    if (longest <= maxEdge) {
      if (typeof src.close === 'function') src.close()
      return file
    }

    const scale = maxEdge / longest
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(w * scale)
    canvas.height = Math.round(h * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(src, 0, 0, canvas.width, canvas.height)
    if (typeof src.close === 'function') src.close()

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', QUALITY))
    // 변환 결과가 원본보다 크면(작은 PNG 등) 의미가 없으니 원본을 쓴다.
    if (!blob || blob.size >= file.size) return file

    const name = file.name?.replace(/\.[^.]+$/, '') || 'photo'
    return new File([blob], `${name}.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
  } catch {
    return file
  }
}
