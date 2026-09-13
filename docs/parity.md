# 合成式パリティ検証 (Python core/composite.py vs JS composite.js)

許容誤差: 最大差 <= 2/255, 平均差 <= 0.5/255

| ケース | 最大差 | 平均差 | 判定 |
|---|---|---|---|
| blend_normal w16h16op1.0 | 0 | 0.0000 | PASS |
| blend_add w16h16op1.0 | 0 | 0.0000 | PASS |
| blend_normal w16h16op0.5 | 1 | 0.0010 | PASS |
| blend_add w16h16op0.5 | 0 | 0.0000 | PASS |
| blend_normal w8h8op0.0 | 0 | 0.0000 | PASS |
| blend_add w8h8op0.0 | 0 | 0.0000 | PASS |
| blend_normal w32h24op0.75 | 1 | 0.0007 | PASS |
| blend_add w32h24op0.75 | 0 | 0.0000 | PASS |
