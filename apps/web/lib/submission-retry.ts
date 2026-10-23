type Pending = {body: string; requestId: string};
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function createSubmissionSender(storage: () => StorageLike | null, uuid: () => string) {
  const pending = new Map<string, Pending>();
  const read = (key: string) => {
    let request = pending.get(key);
    try { request ??= JSON.parse(storage()?.getItem(key) ?? 'null') as Pending | undefined; } catch { /* Fall back to memory. */ }
    return request;
  };
  const clear = (key: string, requestId: string) => {
    if (pending.get(key)?.requestId === requestId) pending.delete(key);
    try {
      const saved = JSON.parse(storage()?.getItem(key) ?? 'null') as Pending | null;
      if (saved?.requestId === requestId) storage()?.removeItem(key);
    } catch { /* An unavailable storage backend must not hide a successful turn. */ }
  };
  const send = async <T>(conversationId: string, body: string, post: (requestId: string) => Promise<T>): Promise<T> => {
    const key = `casepilot.submission.v1:${conversationId}`;
    const previous = read(key);
    const request: Pending = previous?.body === body && previous.requestId
      ? previous : {body, requestId: uuid()};
    pending.set(key, request);
    try { storage()?.setItem(key, JSON.stringify(request)); } catch { /* Retry still works in this tab. */ }
    let result: T;
    try { result = await post(request.requestId); }
    catch (error) {
      // Only transport or partial-response failures get an automatic replay.
      // HTTP validation/conflict errors remain visible for the user to correct.
      if (!(error instanceof TypeError || error instanceof SyntaxError)) throw error;
      result = await post(request.requestId);
    }
    clear(key, request.requestId);
    return result;
  };
  const acknowledge = (conversationId: string, acceptedRequestIds: Iterable<string>) => {
    const key = `casepilot.submission.v1:${conversationId}`;
    const request = read(key);
    if (request && new Set(acceptedRequestIds).has(request.requestId)) clear(key, request.requestId);
  };
  return {send, acknowledge};
}
