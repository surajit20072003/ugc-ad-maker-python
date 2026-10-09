fetch("https://openrouter.ai/api/v1/models")
  .then(r => r.json())
  .then(data => {
    data.data.forEach(m => {
      const id = m.id.toLowerCase();
      if (id.includes("luma") || id.includes("runway") || id.includes("haiper") || id.includes("kling") || id.includes("minimax") || id.includes("pika") || id.includes("sora") || id.includes("video")) {
        console.log(m.id);
      }
    });
  });
