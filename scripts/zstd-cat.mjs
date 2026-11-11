// 把 DSH 的会话记录（多段 zstd 帧拼起来的 .jsonl.zstd）解压到 stdout。
// 用在没有 Python zstandard 的环境（DeepSeek Harness 自带的 Python 不能加载第三方原生扩展）：
// Node 24 自带 zstd，但 zstdDecompressSync 只解第一帧，所以这里按帧头算出每帧的长度，逐帧解。
// 用法：node scripts/zstd-cat.mjs <file>
import { readFileSync } from 'node:fs'
import { zstdDecompressSync } from 'node:zlib'

const buf = readFileSync(process.argv[2])
const out = []
let p = 0
while (p + 4 <= buf.length) {
  const magic = buf.readUInt32LE(p)
  if (magic >= 0x184d2a50 && magic <= 0x184d2a5f) {          // 可跳过帧：4 字节魔数 + 4 字节长度
    p += 8 + buf.readUInt32LE(p + 4)
    continue
  }
  if (magic !== 0xfd2fb528) break                              // 后面是半截（正在写）或不是 zstd：到此为止
  const start = p
  const fhd = buf[p + 4]
  const fcsFlag = fhd >> 6, single = (fhd >> 5) & 1, checksum = (fhd >> 2) & 1, didFlag = fhd & 3
  let q = p + 5 + (single ? 0 : 1) + [0, 1, 2, 4][didFlag] + [single ? 1 : 0, 2, 4, 8][fcsFlag]
  let last = 0
  while (!last) {
    if (q + 3 > buf.length) { q = -1; break }
    const h = buf[q] | (buf[q + 1] << 8) | (buf[q + 2] << 16)
    last = h & 1
    const type = (h >> 1) & 3, size = h >>> 3
    q += 3 + (type === 1 ? 1 : size)
  }
  if (q < 0) break
  q += checksum ? 4 : 0
  if (q > buf.length) break
  try {
    out.push(zstdDecompressSync(buf.subarray(start, q)))
  } catch {
    break
  }
  p = q
}
process.stdout.write(Buffer.concat(out))
