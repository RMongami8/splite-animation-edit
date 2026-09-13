/* HTTP API のごく薄いラッパー。プラン §4 のエンドポイントに1対1対応させる。 */
const Api = (() => {
  "use strict";

  async function req(method, path, { json, form, files } = {}) {
    const opts = { method };
    if (form || files) {
      const fd = new FormData();
      if (form) for (const [k, v] of Object.entries(form)) fd.append(k, v);
      if (files) {
        for (const [k, v] of Object.entries(files)) {
          if (Array.isArray(v)) v.forEach((f) => fd.append(k, f));
          else fd.append(k, v);
        }
      }
      opts.body = fd;
    } else if (json !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(json);
    }
    const resp = await fetch(path, opts);
    const body = await resp.json().catch(() => null);
    if (!resp.ok) {
      const msg = body && body.detail ? JSON.stringify(body.detail) : resp.statusText;
      const err = new Error(`${method} ${path} failed: ${resp.status} ${msg}`);
      err.status = resp.status;
      err.code = body && body.detail && body.detail.code;
      throw err;
    }
    return body;
  }

  return {
    health: () => req("GET", "/api/health"),
    listAssets: (kind) => req("GET", "/api/assets" + (kind ? `?kind=${kind}` : "")),
    getAssetFrames: (id) => req("GET", `/api/assets/${id}/frames`),
    getFrameScores: (id) => req("GET", `/api/assets/${id}/frame_scores`),
    matteProviders: () => req("GET", "/api/matte/providers"),
    matte: (compId, body) => req("POST", `/api/comps/${compId}/matte`, { json: body }),
    uploadAsset: (file) => req("POST", "/api/assets/upload", { files: { file } }),
    importAsset: (type, params, fileFields) =>
      req("POST", "/api/assets/import", {
        form: { type, params_json: JSON.stringify(params) },
        files: fileFields,
      }),
    createComp: (body) => req("POST", "/api/comps", { json: body }),
    getComp: (id) => req("GET", `/api/comps/${id}`),
    patchComp: (id, body) => req("PATCH", `/api/comps/${id}`, { json: body }),
    createLayer: (compId, body) => req("POST", `/api/comps/${compId}/layers`, { json: body }),
    patchLayer: (id, body) => req("PATCH", `/api/layers/${id}`, { json: body }),
    deleteLayer: (id) => req("DELETE", `/api/layers/${id}`),
    putExposures: (layerId, exposures) =>
      req("PUT", `/api/layers/${layerId}/exposures`, { json: { exposures } }),
    patchExposure: (id, body) => req("PATCH", `/api/exposures/${id}`, { json: body }),
    replaceExposure: (id, file) =>
      req("POST", `/api/exposures/${id}/replace`, { files: { file } }),
  };
})();
