type Pending = {body: string; requestId: string};
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function createSubmissionSender(storage: () => StorageLike | null, uuid: () => string) {
  const pending = new Map<string, Pending>();
  return async function send<T>(conversationId: string, body: string, post: (requestId: string) => Promise<T>): Promise<T> {
    const key = `casepilot.submission.v1:${conversationId}`;
    let previous = pending.get(key);
    try { previous ??= JSON.parse(storage()?.getItem(key) ?? 'null') as Pending | undefined; } catch { /* Fall back to memory. */ }
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
    if (pending.get(key)?.requestId === request.requestId) pending.delete(key);
    try {
      const saved = JSON.parse(storage()?.getItem(key) ?? 'null') as Pending | null;
      if (saved?.requestId === request.requestId) storage()?.removeItem(key);
    } catch { /* An unavailable storage backend must not hide a successful turn. */ }
    return result;
  };
}
