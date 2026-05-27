"use client";
import { useEffect, useState } from "react";

export function CountdownTimer({ deadline }: { deadline: string }) {
  const [left, setLeft] = useState(0);

  useEffect(() => {
    const calc = () =>
      setLeft(Math.max(0, new Date(deadline).getTime() - Date.now()));
    calc();
    const t = setInterval(calc, 1000);
    return () => clearInterval(t);
  }, [deadline]);

  const h = Math.floor(left / 3600000);
  const m = Math.floor((left % 3600000) / 60000);
  const s = Math.floor((left % 60000) / 1000);
  const urgent = left < 1800000;

  return (
    <div
      className={`flex items-center gap-2 font-mono text-lg ${
        urgent ? "text-red-400" : "text-amber-400"
      }`}
    >
      {[h, m, s].map((v, i) => (
        <span key={i} className="flex flex-col items-center">
          <span className="bg-zinc-800 px-3 py-1.5 rounded-lg min-w-[3rem] text-center">
            {String(v).padStart(2, "0")}
          </span>
          <span className="text-zinc-600 text-[10px] mt-1">
            {["HRS", "MIN", "SEC"][i]}
          </span>
        </span>
      ))}
    </div>
  );
}
