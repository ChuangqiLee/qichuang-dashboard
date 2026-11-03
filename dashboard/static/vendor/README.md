# Bundled front-end libraries · 随大屏提供的前端库

`index.html` loads these three files from this folder, so the dashboard needs no CDN and also works offline or on
an intranet. 大屏直接从本目录加载以下三个文件，不依赖 CDN，内网 / 离线也能用。

| File | Library | License | SRI hash (sha512) |
|---|---|---|---|
| `echarts-5.5.0.min.js` | Apache ECharts 5.5.0 (`dist/echarts.min.js`) | Apache-2.0 (`LICENSE-echarts.txt`, `NOTICE-echarts.txt`; embedded d3 parts: BSD-3-Clause, `LICENSE-echarts-d3.txt`) | `sha512-k37wQcV4v2h6jgYf5IUz1MoSKPpDs630XGSmCaCCOXxy2awgAWKHGZWr9nMyGgk3IOxA1NxdkN8r1JHgkUtMoQ==` |
| `marked-12.0.2.min.js` | marked 12.0.2 (`marked.min.js`) | MIT (`LICENSE-marked.md`) | `sha512-xeUh+KxNyTufZOje++oQHstlMQ8/rpyzPuM+gjMFYK3z5ILJGE7l2NvYL+XfliKURMpBIKKp1XoPN/qswlSMFA==` |
| `purify-3.1.6.min.js` | DOMPurify 3.1.6 (`dist/purify.min.js`) | Apache-2.0 or MPL-2.0 (`LICENSE-dompurify.txt`) | `sha512-jB0TkTBeQC9ZSkBqDhdmfTv1qdfbWpGE72yJ/01Srq6hEzZIz2xkz1e57p9ai7IeHMwEG7HpzG6NdptChif5Pg==` |

Provenance (2026-11-03): each file is byte-identical to the copy in the npm registry tarball (`echarts-5.5.0.tgz`,
`marked-12.0.2.tgz`, `dompurify-3.1.6.tgz`, whose sha512 matched the registry's `dist.integrity`) and to
`https://cdnjs.cloudflare.com/ajax/libs/<name>/<version>/…`. The license files come from the same tarballs.

Check a file: `openssl dgst -sha512 -binary echarts-5.5.0.min.js | openssl base64 -A` must print the hash above
without the `sha512-` prefix.

To use a CDN instead (smaller download for the kit, but the page then depends on that CDN), point the three
`<script src>` tags in `index.html` back at cdnjs and keep the SRI attribute, for example
`<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js" integrity="sha512-k37w…MoQ==" crossorigin="anonymous" referrerpolicy="no-referrer" defer></script>`.
To upgrade a library, replace the file, update its name in `index.html` and the hash in this table.
