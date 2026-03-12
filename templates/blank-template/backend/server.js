import express from "express";

const app = express();
const PORT = process.env.PORT || 8000;

app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

app.get("/api", (req, res) => {
  res.json({ message: "DreamPilot backend running" });
});

app.listen(PORT, () => {
  console.log(`Backend running on port ${PORT}`);
});
