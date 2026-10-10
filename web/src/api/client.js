const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const defaultApiUrl = import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin;
const resolvedApiUrl = new URL(configuredApiUrl || defaultApiUrl, window.location.origin);
if (window.location.protocol === 'https:' && resolvedApiUrl.protocol !== 'https:') {
  throw new Error('VITE_API_URL deve usar HTTPS quando o dashboard é servido por HTTPS.');
}
export const API_BASE_URL = resolvedApiUrl.toString().replace(/\/+$/, '');
export const API_PREFIX = '/api/v1';

const STATUS_MESSAGES = {
  400: 'A solicitação não pôde ser aceita. Revise os dados e tente novamente.',
  401: 'Sua sessão expirou. Entre novamente com o Discord.',
  403: 'Você não tem permissão para realizar esta operação.',
  404: 'O recurso solicitado não foi encontrado ou não está disponível neste servidor.',
  409: 'Os dados foram alterados em paralelo. Atualize a tela e tente novamente.',
  422: 'Alguns valores são inválidos. Revise os campos e tente novamente.',
};

export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export function apiUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${API_PREFIX}${normalizedPath}`;
}

export async function apiRequest(path, options = {}) {
  const { token, headers: suppliedHeaders, body, signal, ...fetchOptions } = options;
  const headers = new Headers(suppliedHeaders || {});
  headers.set('Accept', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
  if (body !== undefined && !isFormData) headers.set('Content-Type', 'application/json');

  let response;
  try {
    response = await fetch(apiUrl(path), {
      ...fetchOptions,
      headers,
      signal,
      body: body === undefined || isFormData || typeof body === 'string' ? body : JSON.stringify(body),
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new ApiError('Não foi possível conectar à API. Verifique a rede e tente novamente.', 0);
  }

  if (response.status === 204) return null;
  let payload = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('bn:session-expired'));
    }
    const safeDetail = typeof payload?.detail === 'string' && response.status >= 400 && response.status < 500
      ? payload.detail
      : null;
    const message = STATUS_MESSAGES[response.status] || (response.status >= 500
      ? 'A API encontrou um problema inesperado. Tente novamente mais tarde.'
      : 'A solicitação não pôde ser concluída.');
    throw new ApiError(safeDetail || message, response.status, payload);
  }
  return payload;
}

export function getApiErrorMessage(error) {
  if (error instanceof ApiError) return error.message;
  if (error?.name === 'AbortError') return 'A solicitação foi cancelada.';
  return 'Ocorreu um erro inesperado. Tente novamente.';
}
