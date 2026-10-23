// 최신 릴리스를 GitHub에 물어 내려받기 단추를 설치 파일로 바로 연결한다. 실패하면 릴리스 페이지 링크 그대로.
fetch("https://api.github.com/repos/ktu0216/poe2-saegida/releases/latest")
  .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
  .then((rel) => {
    const pick = {
      setup: rel.assets.find((a) => /setup.*\.exe$/.test(a.name)),
      portable: rel.assets.find((a) => /portable.*\.zip$/.test(a.name)),
    };
    document.querySelectorAll("[data-asset]").forEach((el) => {
      const a = pick[el.dataset.asset];
      if (a) el.href = a.browser_download_url;
    });
  })
  .catch(() => {});
