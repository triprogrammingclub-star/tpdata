export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    const expectedToken = env.WORKER_TOKEN || "";
    if (expectedToken) {
      const auth = request.headers.get("Authorization") || "";
      const queryToken = url.searchParams.get("token") || "";
      const bearerToken = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      if (queryToken !== expectedToken && bearerToken !== expectedToken) {
        return new Response("Unauthorized", { status: 401 });
      }
    }

    const file = url.searchParams.get("file") || "";
    const targets = {
      json: {
        url: "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadpara.json",
        type: "application/json; charset=utf-8",
      },
      txt: {
        url: "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadpara.txt",
        type: "text/plain; charset=utf-8",
      },
      genary: {
        url: "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genary.txt",
        type: "text/plain; charset=utf-8",
      },
      areaperc: {
        url: "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/genloadareaperc.csv",
        type: "text/csv; charset=utf-8",
      },
      fueltype: {
        url: "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadfueltype_1.csv",
        type: "text/csv; charset=utf-8",
      },
      areas: {
        url: "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas_1.csv",
        type: "text/csv; charset=utf-8",
      },
    };

    const target = targets[file];
    if (!target) {
      return new Response("Unknown file. Use one of: " + Object.keys(targets).join(", "), { status: 400 });
    }

    const upstream = await fetch(target.url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Referer": "https://www.taipower.com.tw/d006/loadGraph/loadGraph/load_graph.html",
        "Accept": "application/json,text/csv,text/plain,*/*",
        "Cache-Control": "no-cache",
      },
      cf: { cacheTtl: 0, cacheEverything: false },
    });

    const body = await upstream.arrayBuffer();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") || target.type,
        "cache-control": "no-store",
        "x-upstream-status": String(upstream.status),
      },
    });
  },
};
