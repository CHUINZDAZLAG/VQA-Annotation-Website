const configuredApiBaseUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').trim().replace(/\/$/, '');

function apiUrl(path) {
  try {
    return new URL(path, `${configuredApiBaseUrl}/`).toString();
  } catch {
    throw new Error(
      'VITE_API_URL is invalid. Set it to https://vqa-annotation-api.onrender.com in Vercel and redeploy.',
    );
  }
}
const portalKeys = {
  user: { access: 'vqa_user_access_token', refresh: 'vqa_user_refresh_token' },
  admin: { access: 'vqa_admin_access_token', refresh: 'vqa_admin_refresh_token' },
};

async function request(path, options = {}, portal = 'user') {
  const keys = portalKeys[portal];
  const accessToken = localStorage.getItem(keys.access);
  const headers = new Headers(options.headers);
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);

  const response = await fetch(apiUrl(path), {
    ...options,
    headers,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? 'Request failed.');
  }

  return response.status === 204 ? null : response.json();
}

export const authService = {
  async loginWithGoogle(idToken) {
    const authentication = await request('/api/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: idToken }),
    });
    localStorage.setItem(portalKeys.user.access, authentication.access_token);
    localStorage.setItem(portalKeys.user.refresh, authentication.refresh_token);
    return authentication.user;
  },
  async loginAdmin(email, password) {
    const authentication = await request('/api/admin/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    localStorage.setItem(portalKeys.admin.access, authentication.access_token);
    localStorage.setItem(portalKeys.admin.refresh, authentication.refresh_token);
    return authentication.user;
  },
  async refresh(portal = 'user') {
    const refreshToken = localStorage.getItem(portalKeys[portal].refresh);
    if (!refreshToken) throw new Error('No refresh token is available.');
    const authentication = await request(portal === 'admin' ? '/api/admin/auth/refresh' : '/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    localStorage.setItem(portalKeys[portal].access, authentication.access_token);
    localStorage.setItem(portalKeys[portal].refresh, authentication.refresh_token);
    return authentication.user;
  },
  getCurrentUser: () => request('/api/auth/me', {}, 'user'),
  getGoogleDriveConnection: (portal = 'user') => request('/api/auth/google/drive/status', {}, portal),
  startGoogleDriveConnection: (returnPath, portal = 'user') => request(
    `/api/auth/google?return_path=${encodeURIComponent(returnPath)}`,
    {},
    portal,
  ),
  disconnectGoogleDrive: (portal = 'user') => request('/api/auth/google/drive', { method: 'DELETE' }, portal),
  getCurrentAdmin: () => request('/api/admin/auth/me', {}, 'admin'),
  async logout(portal = 'user') {
    try {
      await request(portal === 'admin' ? '/api/admin/auth/logout' : '/api/auth/logout', { method: 'POST' }, portal);
    } finally {
      localStorage.removeItem(portalKeys[portal].access);
      localStorage.removeItem(portalKeys[portal].refresh);
    }
  },
  listAdminTasks: () => request('/api/admin/tasks', {}, 'admin'),
  createAdminTask: (payload) => request('/api/admin/tasks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }, 'admin'),
  getAdminTask: (taskId) => request(`/api/admin/tasks/${taskId}`, {}, 'admin'),
  updateAdminTask: (taskId, payload) => request(`/api/admin/tasks/${taskId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }, 'admin'),
  archiveAdminTask: (taskId) => request(`/api/admin/tasks/${taskId}`, { method: 'DELETE' }, 'admin'),
  deleteAdminTaskPermanently: (taskId) => request(`/api/admin/tasks/${taskId}/permanent`, { method: 'DELETE' }, 'admin'),
  listAdminUsers: () => request('/api/admin/users', {}, 'admin'),
  updateAdminUserStatus: (userId, isActive) => request(`/api/admin/users/${userId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  }, 'admin'),
  getAdminResults: (taskId, filters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '' && value != null));
    return request(`/api/admin/tasks/${taskId}/results${query.toString() ? `?${query}` : ''}`, {}, 'admin');
  },
  getGlobalDashboard: (filters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '' && value != null));
    return request(`/api/admin/dashboard${query.toString() ? `?${query}` : ''}`, {}, 'admin');
  },
  getTaskStatistics: (taskId) => request(`/api/admin/tasks/${taskId}/statistics`, {}, 'admin'),
  listTaskExports: (taskId) => request(`/api/admin/tasks/${taskId}/exports`, {}, 'admin'),
  exportTask: (taskId, format = 'JSON') => request(`/api/admin/tasks/${taskId}/export`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format }),
  }, 'admin'),
  setTaskDriveFolder: (taskId, driveFolderId) => request(`/api/admin/tasks/${taskId}/drive-folder`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ drive_folder_id: driveFolderId }),
  }, 'admin'),
  downloadTaskExport: async (taskId, exportId) => {
    const response = await fetch(apiUrl(`/api/admin/tasks/${taskId}/exports/${exportId}/download`), {
      headers: { Authorization: `Bearer ${localStorage.getItem(portalKeys.admin.access)}` },
    });
    if (!response.ok) throw new Error('Could not download export.');
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = 'task-export'; link.click(); URL.revokeObjectURL(url);
  },
  listTasks: () => request('/api/tasks'),
  getTask: (taskId) => request(`/api/tasks/${taskId}`),
  getTaskDocument: (taskId) => request(`/api/tasks/${taskId}/document`),
  listTaskDrivePdfs: (taskId, folderId) => request(`/api/tasks/${taskId}/document/drive-files?folder_id=${encodeURIComponent(folderId)}`),
  processTaskDrivePdf: (taskId, payload) => request(`/api/tasks/${taskId}/document/select`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  saveTaskDriveLink: (taskId, driveLink) => request(`/api/tasks/${taskId}/document/drive-link`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ drive_link: driveLink }),
  }),
  getTaskSlides: (taskId) => request(`/api/tasks/${taskId}/slides`),
  async uploadTaskDocument(taskId, file, slideName, destinationDriveFolderId) {
    const formData = new FormData();
    formData.append('document', file);
    formData.append('slide_name', slideName);
    if (destinationDriveFolderId) formData.append('destination_drive_folder_id', destinationDriveFolderId);
    return request(`/api/tasks/${taskId}/document`, { method: 'POST', body: formData });
  },
  getTaskSlide: (taskId, slideId) => request(`/api/tasks/${taskId}/slides/${slideId}`),
  saveTaskSlideAnnotation: (taskId, slideId, payload) => request(`/api/tasks/${taskId}/slides/${slideId}/annotation`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  importTaskSlideAnnotations: (taskId, slideId, annotations) => request(`/api/tasks/${taskId}/slides/${slideId}/annotations/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ annotations }),
  }),
  deleteTaskSlideAnnotation: (taskId, slideId, annotationId) => request(`/api/tasks/${taskId}/slides/${slideId}/annotations/${annotationId}`, {
    method: 'DELETE',
  }),
  saveTaskDraftPosition: (taskId, slideId) => request(`/api/tasks/${taskId}/draft-position`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slide_id: slideId }),
  }),
  generateTaskSlideAnnotation: (taskId, slideId, payload) => request(`/api/tasks/${taskId}/slides/${slideId}/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  getReviewSlides: (taskId) => request(`/api/tasks/${taskId}/review/slides`),
  getBlindSlides: (taskId) => request(`/api/tasks/${taskId}/blind/slides`),
  saveBlindAnnotation: (taskId, slideId, payload) => request(`/api/tasks/${taskId}/slides/${slideId}/blind`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  saveBlindDecision: (taskId, slideId, payload) => request(`/api/tasks/${taskId}/slides/${slideId}/blind-decision`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  reviewSlide: (taskId, slideId, payload) => request(`/api/tasks/${taskId}/slides/${slideId}/review`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  async getReviewSlideImage(taskId, slideId) {
    const response = await fetch(apiUrl(`/api/tasks/${taskId}/review/slides/${slideId}/image`), {
      headers: { Authorization: `Bearer ${localStorage.getItem(portalKeys.user.access)}` },
    });
    if (!response.ok) throw new Error('Could not load review slide image.');
    return URL.createObjectURL(await response.blob());
  },
  async getBlindSlideImage(taskId, slideId) {
    const response = await fetch(apiUrl(`/api/tasks/${taskId}/blind/slides/${slideId}/image`), {
      headers: { Authorization: `Bearer ${localStorage.getItem(portalKeys.user.access)}` },
    });
    if (!response.ok) throw new Error('Could not load blind annotation slide image.');
    return URL.createObjectURL(await response.blob());
  },
  submitTaskAnnotation: (taskId) => request(`/api/tasks/${taskId}/submit`, { method: 'POST' }),
  async getTaskSlideImage(taskId, slideId) {
    const response = await fetch(apiUrl(`/api/tasks/${taskId}/slides/${slideId}/image`), {
      headers: { Authorization: `Bearer ${localStorage.getItem(portalKeys.user.access)}` },
    });
    if (!response.ok) throw new Error('Could not load slide image.');
    return URL.createObjectURL(await response.blob());
  },
};
