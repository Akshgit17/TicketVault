"use client";
import { useRef, useState } from "react";
import { Upload, X, CheckCircle } from "lucide-react";
import clsx from "clsx";

interface QRUploadProps {
  count: number;
  onChange: (files: File[]) => void;
}

export function QRUpload({ count, onChange }: QRUploadProps) {
  const [files, setFiles] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const merged = [...files, ...Array.from(incoming)].slice(0, count);
    setFiles(merged);
    onChange(merged);
  };

  const remove = (i: number) => {
    const next = files.filter((_, idx) => idx !== i);
    setFiles(next);
    onChange(next);
  };

  const complete = files.length === count && count > 0;

  return (
    <div className="space-y-3">
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleFiles(e.dataTransfer.files);
        }}
        className={clsx(
          "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
          complete
            ? "border-amber-500 bg-amber-500/5"
            : "border-zinc-700 hover:border-zinc-500 bg-zinc-900"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        {complete ? (
          <CheckCircle className="w-8 h-8 text-amber-400 mx-auto mb-2" />
        ) : (
          <Upload className="w-8 h-8 text-zinc-500 mx-auto mb-2" />
        )}
        <p className="text-sm text-zinc-400">
          {complete
            ? `${count} QR code${count > 1 ? "s" : ""} ready`
            : `Upload ${count} QR image${count > 1 ? "s" : ""} · drag or click`}
        </p>
        <p className="text-xs text-zinc-600 mt-1">PNG, JPG accepted</p>
      </div>

      {files.length > 0 && (
        <div className="grid grid-cols-4 gap-2">
          {files.map((f, i) => (
            <div
              key={i}
              className="relative group rounded-lg overflow-hidden aspect-square bg-zinc-800"
            >
              <img
                src={URL.createObjectURL(f)}
                alt=""
                className="w-full h-full object-cover"
              />
              <button
                onClick={() => remove(i)}
                className="absolute top-1 right-1 bg-zinc-900/80 rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X className="w-3 h-3 text-zinc-300" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
