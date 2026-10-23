export const attachmentAccept = ".pdf,.txt,.xlsx,.xls,.png,.jpg,.jpeg,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,image/png,image/jpeg";
export const isImageAttachment = (file: { name?: string; mime_type?: string; type?: string }) =>
  (file.mime_type ?? file.type ?? "").toLowerCase().startsWith("image/") ||
  /\.(png|jpe?g)$/i.test(file.name ?? "");
export function clipboardImages(data: DataTransfer): File[] {
  return Array.from(data.items).filter(item =>
    item.kind === "file" && ["image/png", "image/jpeg"].includes(item.type.toLowerCase()))
    .map(item => item.getAsFile()).filter((file): file is File => file !== null);
}
