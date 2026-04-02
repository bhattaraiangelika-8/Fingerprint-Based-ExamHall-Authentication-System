/**
 * BiometriQ — SPA JavaScript
 * Handles routing, API calls, form submissions, and UI interactions.
 */

'use strict';

/* ═══════════════════════════════════════════
   CSRF TOKEN
   ═══════════════════════════════════════════ */
function getCsrf() {
  const meta = document.querySelector('[name=csrfmiddlewaretoken]');
  if (meta) return meta.value;
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : '';
}

/* ═══════════════════════════════════════════
   API HELPERS
   ═══════════════════════════════════════════ */
const API = {
  base: '/api',

  async get(path) {
    const res = await fetch(this.base + path, {
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin',
    });
    const data = await res.json();
    if (!res.ok) throw Object.assign(new Error(data.error || data.detail || 'Request failed'), { data });
    return data;
  },

  async post(path, body) {
    const isFormData = body instanceof FormData;
    const headers = { 'X-CSRFToken': getCsrf(), 'Accept': 'application/json' };
    if (!isFormData) headers['Content-Type'] = 'application/json';

    const res = await fetch(this.base + path, {
      method: 'POST',
      headers,
      body: isFormData ? body : JSON.stringify(body),
      credentials: 'same-origin',
    });
    const data = await res.json();
    if (!res.ok) throw Object.assign(new Error(data.error || data.detail || 'Request failed'), { data });
    return data;
  },

  async delete(path) {
    const res = await fetch(this.base + path, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': getCsrf(), 'Accept': 'application/json' },
      credentials: 'same-origin',
    });
    if (!res.ok) {
      let msg = 'Delete failed';
      try { const d = await res.json(); msg = d.error || d.detail || msg; } catch {}
      throw new Error(msg);
    }
    return true;
  },
};

/* ═══════════════════════════════════════════
   TOAST SYSTEM
   ═══════════════════════════════════════════ */
const Toast = {
  container: null,
  init() { this.container = document.getElementById('toast-container'); },

  show(message, type = 'info', duration = 4500) {
    const icons = {
      success: `<svg class="toast-icon" viewBox="0 0 20 20" fill="currentColor" style="color:#10b981"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/></svg>`,
      error:   `<svg class="toast-icon" viewBox="0 0 20 20" fill="currentColor" style="color:#ef4444"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"/></svg>`,
      info:    `<svg class="toast-icon" viewBox="0 0 20 20" fill="currentColor" style="color:#3b82f6"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z"/></svg>`,
    };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `${icons[type] || icons.info}<span class="toast-text">${message}</span><button class="toast-dismiss" aria-label="Dismiss">&times;</button>`;
    el.querySelector('.toast-dismiss').onclick = () => this.remove(el);
    this.container.appendChild(el);
    setTimeout(() => this.remove(el), duration);
  },

  remove(el) {
    el.classList.add('removing');
    setTimeout(() => el.remove(), 200);
  },
};

/* ═══════════════════════════════════════════
   ROUTER (SPA page switching)
   ═══════════════════════════════════════════ */
const Router = {
  current: 'register',

  navigate(page) {
    // Hide all pages
    document.querySelectorAll('.page').forEach(p => {
      p.classList.remove('active');
      p.classList.add('hidden');
    });
    // Show target
    const target = document.getElementById(`page-${page}`);
    if (target) {
      target.classList.remove('hidden');
      // Force reflow for animation
      void target.offsetWidth;
      target.classList.add('active');
    }
    // Update nav
    document.querySelectorAll('.nav-item').forEach(n => {
      n.classList.toggle('active', n.dataset.page === page);
      n.setAttribute('aria-current', n.dataset.page === page ? 'page' : 'false');
    });
    this.current = page;

    // Side-effects per page
    if (page === 'students') Students.load();

    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
  },
};

/* ═══════════════════════════════════════════
   REGISTER STUDENT
   ═══════════════════════════════════════════ */
const Register = {
  lastStudentId: null,

  init() {
    const form = document.getElementById('register-form');
    form.addEventListener('submit', e => { e.preventDefault(); this.submit(); });

    // Photo upload
    const zone = document.getElementById('photo-upload-zone');
    const input = document.getElementById('reg-photo');
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') input.click(); });
    input.addEventListener('change', () => this.previewPhoto(input.files[0]));

    // Drag & drop for photo
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) {
        input.files = e.dataTransfer.files;
        this.previewPhoto(file);
      }
    });

    // Go-to-enroll from success card
    document.getElementById('go-enroll-btn').addEventListener('click', () => {
      if (this.lastStudentId) {
        document.getElementById('enroll-student-id').value = this.lastStudentId;
        Enroll.lookupStudent(this.lastStudentId);
      }
      Router.navigate('enroll');
    });
  },

  previewPhoto(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      const img = document.getElementById('photo-preview-img');
      const placeholder = document.getElementById('photo-placeholder');
      img.src = e.target.result;
      img.classList.remove('hidden');
      placeholder.style.display = 'none';
    };
    reader.readAsDataURL(file);
  },

  clearErrors() {
    document.querySelectorAll('.field-error').forEach(e => e.textContent = '');
    document.querySelectorAll('.form-input.error').forEach(e => e.classList.remove('error'));
  },

  showError(fieldId, msg) {
    const errEl = document.getElementById(`err-${fieldId}`);
    const inputEl = document.getElementById(`reg-${fieldId}`);
    if (errEl) errEl.textContent = msg;
    if (inputEl) inputEl.classList.add('error');
  },

  validate() {
    this.clearErrors();
    let ok = true;
    const regNo = document.getElementById('reg-registration-no').value.trim();
    const name  = document.getElementById('reg-full-name').value.trim();
    if (!regNo) { this.showError('registration-no', 'Registration number is required'); ok = false; }
    if (!name)  { this.showError('full-name', 'Full name is required'); ok = false; }
    return ok;
  },

  async submit() {
    if (!this.validate()) return;
    const btn = document.getElementById('reg-submit-btn');
    btn.classList.add('loading');
    btn.disabled = true;

    try {
      const fd = new FormData(document.getElementById('register-form'));
      // Remove csrf from FormData key (Django reads from header)
      fd.delete('csrfmiddlewaretoken');

      // Handle consent checkbox
      const consent = document.getElementById('reg-consent').checked;
      fd.set('consent_signed', consent ? 'true' : 'false');

      const data = await API.post('/students/', fd);
      this.lastStudentId = data.student_id;
      this.showSuccess(data);
      Toast.show('Student registered successfully!', 'success');
      document.getElementById('register-form').reset();
      // Reset photo preview
      document.getElementById('photo-preview-img').classList.add('hidden');
      document.getElementById('photo-placeholder').style.display = '';
    } catch (err) {
      const msg = this.buildErrorMsg(err);
      Toast.show(msg, 'error');
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  },

  buildErrorMsg(err) {
    if (err.data) {
      // Show field errors inline
      const fields = {
        registration_no: 'registration-no',
        full_name: 'full-name',
      };
      for (const [apiField, uiField] of Object.entries(fields)) {
        if (err.data[apiField]) {
          this.showError(uiField, Array.isArray(err.data[apiField]) ? err.data[apiField][0] : err.data[apiField]);
        }
      }
      if (err.data.non_field_errors) return err.data.non_field_errors[0];
    }
    return err.message || 'Registration failed. Please try again.';
  },

  showSuccess(data) {
    const card = document.getElementById('reg-success-card');
    const detail = document.getElementById('reg-success-detail');
    detail.innerHTML = `
      <strong>Student ID:</strong> ${data.student_id}<br>
      <strong>Name:</strong> ${data.full_name || '—'}<br>
      <strong>Reg No:</strong> ${data.registration_no || '—'}
    `;
    card.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },
};

/* ═══════════════════════════════════════════
   ENROLL FINGERPRINT
   ═══════════════════════════════════════════ */
const Enroll = {
  init() {
    const form = document.getElementById('enroll-form');
    form.addEventListener('submit', e => { e.preventDefault(); this.submit(); });

    // Lookup button
    document.getElementById('lookup-student-btn').addEventListener('click', () => {
      const id = parseInt(document.getElementById('enroll-student-id').value);
      if (id) this.lookupStudent(id);
    });
    document.getElementById('enroll-student-id').addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const id = parseInt(e.target.value);
        if (id) this.lookupStudent(id);
      }
    });

    // Fingerprint dropzone
    const zone  = document.getElementById('fingerprint-dropzone');
    const input = document.getElementById('enroll-fingerprint');
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') input.click(); });
    input.addEventListener('change', () => this.previewFingerprint(input.files[0]));
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) {
        input.files = e.dataTransfer.files;
        this.previewFingerprint(file);
      }
    });
  },

  previewFingerprint(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      const img     = document.getElementById('fingerprint-preview');
      const inner   = document.getElementById('dropzone-inner');
      const dropzone = document.getElementById('fingerprint-dropzone');
      img.src = e.target.result;
      img.classList.remove('hidden');
      inner.style.display = 'none';
      dropzone.classList.add('has-file');
    };
    reader.readAsDataURL(file);
  },

  async lookupStudent(id) {
    const badge = document.getElementById('student-badge');
    try {
      const data = await API.get(`/students/${id}/`);
      document.getElementById('student-badge-name').textContent = data.full_name || '—';
      document.getElementById('student-badge-reg').textContent  = data.registration_no || '—';
      const initials = (data.full_name || '?').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
      document.getElementById('student-badge-avatar').textContent = initials;

      // Enrollment status (we don't get fingerprint_template in StudentSerializer,
      // but we can show a generic indicator)
      const statusEl = document.getElementById('student-badge-status');
      statusEl.innerHTML = `<span class="card-badge pending">ID #${data.student_id}</span>`;
      badge.classList.remove('hidden');
      document.getElementById('err-enroll-student-id').textContent = '';
    } catch {
      badge.classList.add('hidden');
      document.getElementById('err-enroll-student-id').textContent = `No student found with ID ${id}`;
    }
  },

  async submit() {
    const idInput = document.getElementById('enroll-student-id');
    const imgInput = document.getElementById('enroll-fingerprint');
    let ok = true;

    document.getElementById('err-enroll-student-id').textContent = '';
    document.getElementById('err-fingerprint').textContent = '';

    if (!idInput.value) { document.getElementById('err-enroll-student-id').textContent = 'Student ID is required'; ok = false; }
    if (!imgInput.files || !imgInput.files[0]) { document.getElementById('err-fingerprint').textContent = 'Please select a fingerprint image'; ok = false; }
    if (!ok) return;

    const btn = document.getElementById('enroll-submit-btn');
    btn.classList.add('loading');
    btn.disabled = true;

    try {
      const fd = new FormData();
      fd.append('student_id', idInput.value);
      fd.append('finger_type', 'right_thumb');
      fd.append('fingerprint_image', imgInput.files[0]);

      const data = await API.post('/fingerprint/upload/', fd);
      this.showResult(data, true);
      Toast.show(`Fingerprint enrolled! ${data.minutiae_count} minutiae detected.`, 'success');
    } catch (err) {
      this.showResult(null, false, err.message || 'Enrollment failed');
      Toast.show(err.message || 'Enrollment failed. Please try again.', 'error');
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  },

  showResult(data, success, errorMsg = '') {
    const placeholder = document.getElementById('enroll-placeholder');
    const result      = document.getElementById('enroll-result');
    const badge       = document.getElementById('result-badge');
    const badgeText   = document.getElementById('result-badge-text');

    placeholder.classList.add('hidden');
    result.classList.remove('hidden');

    if (success && data) {
      badge.className = 'result-badge success';
      badgeText.textContent = 'Enrolled Successfully';

      document.getElementById('result-minutiae').textContent = data.minutiae_count ?? '—';
      document.getElementById('result-steps').textContent    = data.preprocessing_steps ?? '—';

      const q = data.quality || {};
      const score = Math.round(q.overall_score ?? 0);
      document.getElementById('result-quality-score').textContent = `${score} / 100`;
      document.getElementById('result-blur').textContent           = formatScore(q.blur_score);
      document.getElementById('result-contrast').textContent       = formatScore(q.contrast_score);
      document.getElementById('result-edge').textContent           = formatScore(q.edge_density);

      setTimeout(() => {
        document.getElementById('result-quality-bar').style.width = `${Math.min(score, 100)}%`;
      }, 100);
    } else {
      badge.className = 'result-badge error';
      badge.querySelector('svg').innerHTML = `<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"/>`;
      badgeText.textContent = errorMsg || 'Enrollment Failed';
      ['result-minutiae','result-quality-score','result-blur','result-contrast','result-edge','result-steps']
        .forEach(id => { document.getElementById(id).textContent = '—'; });
      document.getElementById('result-quality-bar').style.width = '0%';
    }
  },
};

function formatScore(val) {
  if (val === undefined || val === null) return '—';
  return typeof val === 'number' ? val.toFixed(1) : val;
}

/* ═══════════════════════════════════════════
   STUDENT LIST
   ═══════════════════════════════════════════ */
const Students = {
  all: [],
  filtered: [],
  modalStudentId: null,

  init() {
    document.getElementById('refresh-students-btn').addEventListener('click', () => this.load());
    document.getElementById('student-search').addEventListener('input', e => this.filter(e.target.value));

    // Modal
    document.getElementById('modal-close').addEventListener('click', () => this.closeModal());
    document.getElementById('modal-overlay').addEventListener('click', e => {
      if (e.target === document.getElementById('modal-overlay')) this.closeModal();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') this.closeModal();
    });

    document.getElementById('modal-enroll-btn').addEventListener('click', () => {
      if (this.modalStudentId) {
        document.getElementById('enroll-student-id').value = this.modalStudentId;
        Enroll.lookupStudent(this.modalStudentId);
        this.closeModal();
        Router.navigate('enroll');
      }
    });

    document.getElementById('modal-delete-btn').addEventListener('click', () => {
      if (this.modalStudentId) this.deleteStudent(this.modalStudentId);
    });
  },

  async load() {
    const grid    = document.getElementById('student-grid');
    const loading = document.getElementById('students-loading');
    const empty   = document.getElementById('students-empty');

    // Remove old cards
    grid.querySelectorAll('.student-card').forEach(c => c.remove());
    loading.classList.remove('hidden');
    empty.classList.add('hidden');

    try {
      const data = await API.get('/students/');
      this.all = Array.isArray(data) ? data : (data.results || []);
      this.filtered = [...this.all];
      this.updateStats();
      this.render();
    } catch (err) {
      Toast.show('Failed to load students: ' + err.message, 'error');
    } finally {
      loading.classList.add('hidden');
    }
  },

  updateStats() {
    const total    = this.all.length;
    // We don't have enrolled flag in the list serializer, show total for now
    document.getElementById('stat-total').textContent    = total;
    document.getElementById('stat-enrolled').textContent = '—';
    document.getElementById('stat-pending').textContent  = '—';
  },

  filter(query) {
    const q = query.toLowerCase().trim();
    this.filtered = q
      ? this.all.filter(s =>
          (s.full_name || '').toLowerCase().includes(q) ||
          (s.registration_no || '').toLowerCase().includes(q) ||
          (s.college_name || '').toLowerCase().includes(q)
        )
      : [...this.all];
    this.render();
  },

  render() {
    const grid  = document.getElementById('student-grid');
    const empty = document.getElementById('students-empty');

    grid.querySelectorAll('.student-card').forEach(c => c.remove());

    if (this.filtered.length === 0) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');

    this.filtered.forEach(s => {
      const card = this.buildCard(s);
      grid.appendChild(card);
    });
  },

  buildCard(s) {
    const initials = (s.full_name || '?').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
    const enrolled = false; // No enrollment flag in list endpoint; could be extended
    const card = document.createElement('article');
    card.className = 'student-card';
    card.setAttribute('tabindex', '0');
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', `View details for ${s.full_name}`);
    card.innerHTML = `
      <div class="card-top">
        <div class="card-avatar">${initials}</div>
        <div>
          <div class="card-name">${escHtml(s.full_name || '—')}</div>
          <div class="card-reg">${escHtml(s.registration_no || '—')}</div>
        </div>
        <span class="card-badge ${enrolled ? 'enrolled' : 'pending'}">${enrolled ? '✅ Enrolled' : '⏳ Pending'}</span>
      </div>
      <div class="card-info">
        ${s.college_name ? `<div class="card-info-item"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M10.394 2.08a1 1 0 00-.788 0l-7 3a1 1 0 000 1.84L5.25 8.051a.999.999 0 01.356-.257l4-1.714a1 1 0 11.788 1.838l-2.727 1.17 1.94.831a1 1 0 00.787 0l7-3a1 1 0 000-1.838l-7-3z" /></svg>${escHtml(s.college_name)}</div>` : ''}
        ${s.email ? `<div class="card-info-item"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884zM18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z"/></svg>${escHtml(s.email)}</div>` : ''}
        ${s.phone ? `<div class="card-info-item"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M2 3a1 1 0 011-1h2.153a1 1 0 01.986.836l.74 4.435a1 1 0 01-.54 1.06l-1.548.773a11.037 11.037 0 006.105 6.105l.774-1.548a1 1 0 011.059-.54l4.435.74a1 1 0 01.836.986V17a1 1 0 01-1 1h-2C7.82 18 2 12.18 2 5V3z"/></svg>${escHtml(s.phone)}</div>` : ''}
      </div>
    `;
    const open = () => this.openModal(s);
    card.addEventListener('click', open);
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') open(); });
    return card;
  },

  openModal(s) {
    this.modalStudentId = s.student_id;
    const initials = (s.full_name || '?').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);

    document.getElementById('modal-avatar').textContent = initials;
    document.getElementById('modal-title').textContent  = s.full_name || '—';
    document.getElementById('modal-reg').textContent    = s.registration_no || '—';
    document.getElementById('md-dob').textContent       = s.date_of_birth || '—';
    document.getElementById('md-gender').textContent    = s.gender || '—';
    document.getElementById('md-college').textContent   = s.college_name || '—';
    document.getElementById('md-email').textContent     = s.email || '—';
    document.getElementById('md-phone').textContent     = s.phone || '—';
    document.getElementById('md-created').textContent   = s.created_at ? new Date(s.created_at).toLocaleDateString() : '—';
    document.getElementById('md-id').textContent        = s.student_id;
    document.getElementById('md-consent').textContent   = s.consent_signed ? '✅ Signed' : '❌ Not signed';

    document.getElementById('modal-badge').innerHTML = `<span class="card-badge pending">⏳ Pending Enrollment</span>`;
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('modal-close').focus();
  },

  closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    this.modalStudentId = null;
  },

  async deleteStudent(id) {
    if (!confirm(`Are you sure you want to permanently delete student #${id}? This action cannot be undone.`)) return;
    try {
      await API.delete(`/students/${id}/`);
      Toast.show('Student deleted successfully.', 'success');
      this.closeModal();
      this.load();
    } catch (err) {
      Toast.show('Delete failed: ' + err.message, 'error');
    }
  },
};

/* ═══════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════ */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ═══════════════════════════════════════════
   MOBILE SIDEBAR
   ═══════════════════════════════════════════ */
function initMobileSidebar() {
  const hamburger = document.getElementById('hamburger');
  const sidebar   = document.getElementById('sidebar');
  hamburger.addEventListener('click', () => sidebar.classList.toggle('open'));
}

/* ═══════════════════════════════════════════
   BOOT
   ═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  Toast.init();
  Register.init();
  Enroll.init();
  Students.init();
  initMobileSidebar();

  // Wire nav buttons
  document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
    btn.addEventListener('click', () => Router.navigate(btn.dataset.page));
  });

  // Start on register page
  Router.navigate('register');
});
