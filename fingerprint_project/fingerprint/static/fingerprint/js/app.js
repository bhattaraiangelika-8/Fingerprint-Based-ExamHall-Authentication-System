/**
 * BiometriQ — SPA JavaScript
 * Handles routing, API calls, form submissions, and UI interactions.
 */
'use strict';

/* ─── CSRF TOKEN ─── */
function getCsrf() {
  const meta = document.querySelector('[name=csrfmiddlewaretoken]');
  if (meta) return meta.value;
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : '';
}

/* ─── API HELPERS ─── */
const API = {
  base: '/api',
  async get(path) {
    const res = await fetch(this.base + path, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
    const data = await res.json();
    if (!res.ok) throw Object.assign(new Error(data.error || data.detail || 'Request failed'), { data });
    return data;
  },
  async post(path, body) {
    const isFormData = body instanceof FormData;
    const headers = { 'X-CSRFToken': getCsrf(), Accept: 'application/json' };
    if (!isFormData) headers['Content-Type'] = 'application/json';
    const res = await fetch(this.base + path, { method: 'POST', headers, body: isFormData ? body : JSON.stringify(body), credentials: 'same-origin' });
    const data = await res.json();
    if (!res.ok) throw Object.assign(new Error(data.error || data.detail || 'Request failed'), { data });
    return data;
  },
  async put(path, body) {
    const isFormData = body instanceof FormData;
    const headers = { 'X-CSRFToken': getCsrf(), Accept: 'application/json' };
    if (!isFormData) headers['Content-Type'] = 'application/json';
    const res = await fetch(this.base + path, { method: 'PUT', headers, body: isFormData ? body : JSON.stringify(body), credentials: 'same-origin' });
    const data = await res.json();
    if (!res.ok) throw Object.assign(new Error(data.error || data.detail || 'Request failed'), { data });
    return data;
  },
  async del(path) {
    const res = await fetch(this.base + path, { method: 'DELETE', headers: { 'X-CSRFToken': getCsrf(), Accept: 'application/json' }, credentials: 'same-origin' });
    if (!res.ok) { let msg = 'Delete failed'; try { const d = await res.json(); msg = d.error || d.detail || msg; } catch {} throw new Error(msg); }
    return true;
  },
};

/* ─── TOAST SYSTEM ─── */
const Toast = {
  container: null,
  init() { this.container = document.getElementById('toast-container'); },
  show(message, type = 'info', duration = 4500) {
    const icons = {
      success: '<svg class="toast-icon" viewBox="0 0 20 20" fill="currentColor" style="color:#059669"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/></svg>',
      error: '<svg class="toast-icon" viewBox="0 0 20 20" fill="currentColor" style="color:#dc2626"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"/></svg>',
      info: '<svg class="toast-icon" viewBox="0 0 20 20" fill="currentColor" style="color:#0f766e"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z"/></svg>',
    };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `${icons[type] || icons.info}<span class="toast-text">${message}</span><button class="toast-dismiss" aria-label="Dismiss">&times;</button>`;
    el.querySelector('.toast-dismiss').onclick = () => this.remove(el);
    this.container.appendChild(el);
    setTimeout(() => this.remove(el), duration);
  },
  remove(el) { el.classList.add('removing'); setTimeout(() => el.remove(), 200); },
};

/* ─── ROUTER ─── */
const Router = {
  current: 'register',
  navigate(page) {
    document.querySelectorAll('.page').forEach(p => { p.classList.remove('active'); p.classList.add('hidden'); });
    const target = document.getElementById(`page-${page}`);
    if (target) {
      target.classList.remove('hidden');
      void target.offsetWidth;
      target.classList.add('active');
    }
    document.querySelectorAll('.nav-item').forEach(n => {
      n.classList.toggle('active', n.dataset.page === page);
      n.setAttribute('aria-current', n.dataset.page === page ? 'page' : 'false');
    });
    this.current = page;
    if (page === 'register') Register.loadExams();
    if (page === 'students') Students.load();
    if (page === 'admin') Admin.load();
    if (page === 'exams') ExamManager.load();
    if (page === 'seats') SeatManager.load();
    if (page === 'sessions') SessionsManager.load();
    if (page === 'reports') ReportManager.load();
    document.getElementById('sidebar').classList.remove('open');
  },
};

/* ═══════════════════════════════════════════
   EXISTING: REGISTER STUDENT
   ═══════════════════════════════════════════ */
const Register = {
  lastStudentId: null,
  init() {
    const form = document.getElementById('register-form');
    form.addEventListener('submit', e => { e.preventDefault(); this.submit(); });
    const zone = document.getElementById('photo-upload-zone');
    const input = document.getElementById('reg-photo');
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') input.click(); });
    input.addEventListener('change', () => this.previewPhoto(input.files[0]));
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('drag-over'); const file = e.dataTransfer.files[0]; if (file && file.type.startsWith('image/')) { input.files = e.dataTransfer.files; this.previewPhoto(file); } });
    document.getElementById('go-enroll-btn').addEventListener('click', () => { if (this.lastStudentId) { document.getElementById('enroll-student-id').value = this.lastStudentId; Enroll.lookupStudent(this.lastStudentId); } Router.navigate('enroll'); });
    // Document upload zone
    const docZone = document.getElementById('doc-upload-zone');
    const docInput = document.getElementById('reg-document');
    if (docZone && docInput) {
      docZone.addEventListener('click', () => docInput.click());
      docZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') docInput.click(); });
      docInput.addEventListener('change', function() {
        const placeholder = document.getElementById('doc-placeholder');
        if (this.files && this.files[0]) {
          placeholder.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:32px;height:32px"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg><span>${escHtml(this.files[0].name)}</span>`;
        }
      });
    }
    this.loadExams();
  },
  async loadExams() {
    try {
      const data = await API.get('/exams/');
      const sel = document.getElementById('reg-exams');
      if (!sel) return;
      sel.innerHTML = data.map(e => `<option value="${e.exam_id}">${escHtml(e.subject_name||'')} — ${e.date||''} (${e.start_time||''})</option>`).join('');
    } catch { /* exams not available yet */ }
  },
  previewPhoto(file) { if (!file) return; const reader = new FileReader(); reader.onload = e => { const img = document.getElementById('photo-preview-img'); const placeholder = document.getElementById('photo-placeholder'); img.src = e.target.result; img.classList.remove('hidden'); placeholder.style.display = 'none'; }; reader.readAsDataURL(file); },
  clearErrors() { document.querySelectorAll('.field-error').forEach(e => e.textContent = ''); document.querySelectorAll('.form-input.error').forEach(e => e.classList.remove('error')); },
  showError(fieldId, msg) { const errEl = document.getElementById(`err-${fieldId}`); const inputEl = document.getElementById(`reg-${fieldId}`); if (errEl) errEl.textContent = msg; if (inputEl) inputEl.classList.add('error'); },
  validate() { this.clearErrors(); let ok = true; if (!document.getElementById('reg-registration-no').value.trim()) { this.showError('registration-no', 'Required'); ok = false; } if (!document.getElementById('reg-full-name').value.trim()) { this.showError('full-name', 'Required'); ok = false; } return ok; },
  async submit() {
    if (!this.validate()) return;
    const btn = document.getElementById('reg-submit-btn'); btn.classList.add('loading'); btn.disabled = true;
    try {
      const fd = new FormData(document.getElementById('register-form'));
      fd.delete('csrfmiddlewaretoken');
      fd.set('consent_signed', document.getElementById('reg-consent').checked ? 'true' : 'false');
      const data = await API.post('/register/', fd);
      this.lastStudentId = data.student_id;
      this.showSuccess(data);
      Toast.show('Registration submitted! Status: ' + data.status, 'success');
      document.getElementById('register-form').reset();
      document.getElementById('photo-preview-img').classList.add('hidden');
      document.getElementById('photo-placeholder').style.display = '';
      const docPlaceholder = document.getElementById('doc-placeholder');
      if (docPlaceholder) docPlaceholder.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:32px;height:32px"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg><span>Upload ID / Document</span>';
    } catch (err) { Toast.show(err.message || 'Registration failed', 'error'); }
    finally { btn.classList.remove('loading'); btn.disabled = false; }
  },
  showSuccess(data) {
    const card = document.getElementById('reg-success-card');
    document.getElementById('reg-success-detail').innerHTML = `<strong>Student ID:</strong> ${data.student_id}<br><strong>Status:</strong> ${data.status}`;
    card.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },
};

/* ═══════════════════════════════════════════
   EXISTING: ENROLL FINGERPRINT
   ═══════════════════════════════════════════ */
const Enroll = {
  init() {
    const form = document.getElementById('enroll-form');
    form.addEventListener('submit', e => { e.preventDefault(); this.submit(); });
    document.getElementById('lookup-student-btn').addEventListener('click', () => { const id = parseInt(document.getElementById('enroll-student-id').value); if (id) this.lookupStudent(id); });
    document.getElementById('enroll-student-id').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const id = parseInt(e.target.value); if (id) this.lookupStudent(id); } });
    const zone = document.getElementById('fingerprint-dropzone');
    const input = document.getElementById('enroll-fingerprint');
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') input.click(); });
    input.addEventListener('change', () => this.previewFingerprint(input.files[0]));
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('drag-over'); const file = e.dataTransfer.files[0]; if (file && file.type.startsWith('image/')) { input.files = e.dataTransfer.files; this.previewFingerprint(file); } });
  },
  previewFingerprint(file) { if (!file) return; const reader = new FileReader(); reader.onload = e => { document.getElementById('fingerprint-preview').src = e.target.result; document.getElementById('fingerprint-preview').classList.remove('hidden'); document.getElementById('dropzone-inner').style.display = 'none'; document.getElementById('fingerprint-dropzone').classList.add('has-file'); }; reader.readAsDataURL(file); },
  async lookupStudent(id) {
    try {
      const data = await API.get(`/students/${id}/`);
      document.getElementById('student-badge-name').textContent = data.full_name || '—';
      document.getElementById('student-badge-reg').textContent = data.registration_no || '—';
      const initials = (data.full_name || '?').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
      document.getElementById('student-badge-avatar').textContent = initials;
      document.getElementById('student-badge-status').innerHTML = `<span class="card-badge ${data.status === 'APPROVED' ? 'enrolled' : 'pending'}">${data.status || '—'}</span>`;
      document.getElementById('student-badge').classList.remove('hidden');
      document.getElementById('err-enroll-student-id').textContent = '';
    } catch { document.getElementById('student-badge').classList.add('hidden'); document.getElementById('err-enroll-student-id').textContent = `No student found with ID ${id}`; }
  },
  async submit() {
    const idInput = document.getElementById('enroll-student-id'); const imgInput = document.getElementById('enroll-fingerprint');
    document.getElementById('err-enroll-student-id').textContent = ''; document.getElementById('err-fingerprint').textContent = '';
    if (!idInput.value) { document.getElementById('err-enroll-student-id').textContent = 'Student ID is required'; return; }
    if (!imgInput.files || !imgInput.files[0]) { document.getElementById('err-fingerprint').textContent = 'Please select a fingerprint image'; return; }
    const btn = document.getElementById('enroll-submit-btn'); btn.classList.add('loading'); btn.disabled = true;
    try {
      const fd = new FormData(); fd.append('student_id', idInput.value); fd.append('finger_type', 'right_thumb'); fd.append('fingerprint_image', imgInput.files[0]);
      const data = await API.post('/fingerprint/upload/', fd);
      this.showResult(data, true);
      Toast.show(`Fingerprint enrolled! ${data.minutiae_count} minutiae detected.`, 'success');
    } catch (err) { this.showResult(null, false, err.message || 'Enrollment failed'); Toast.show(err.message || 'Enrollment failed', 'error'); }
    finally { btn.classList.remove('loading'); btn.disabled = false; }
  },
  showResult(data, success, errorMsg = '') {
    const placeholder = document.getElementById('enroll-placeholder'); const result = document.getElementById('enroll-result'); const badge = document.getElementById('result-badge'); const badgeText = document.getElementById('result-badge-text');
    placeholder.classList.add('hidden'); result.classList.remove('hidden');
    if (success && data) {
      badge.className = 'result-badge success'; badgeText.textContent = 'Enrolled Successfully';
      document.getElementById('result-minutiae').textContent = data.minutiae_count ?? '—';
      document.getElementById('result-steps').textContent = data.preprocessing_steps ?? '—';
      const q = data.quality || {}; const score = Math.round(q.overall_score ?? 0);
      document.getElementById('result-quality-score').textContent = `${score} / 100`;
      document.getElementById('result-blur').textContent = formatScore(q.blur_score);
      document.getElementById('result-contrast').textContent = formatScore(q.contrast_score);
      document.getElementById('result-edge').textContent = formatScore(q.edge_density);
      setTimeout(() => { document.getElementById('result-quality-bar').style.width = `${Math.min(score, 100)}%`; }, 100);
    } else {
      badge.className = 'result-badge error'; badgeText.textContent = errorMsg || 'Enrollment Failed';
      ['result-minutiae','result-quality-score','result-blur','result-contrast','result-edge','result-steps'].forEach(id => { document.getElementById(id).textContent = '—'; });
      document.getElementById('result-quality-bar').style.width = '0%';
    }
  },
};
function formatScore(val) { return (val === undefined || val === null) ? '—' : (typeof val === 'number' ? val.toFixed(1) : val); }

/* ═══════════════════════════════════════════
   EXISTING: STUDENT RECORDS
   ═══════════════════════════════════════════ */
const Students = {
  all: [], filtered: [], modalStudentId: null,
  _studentData: null,

  init() {
    document.getElementById('refresh-students-btn').addEventListener('click', () => this.load());
    document.getElementById('student-search').addEventListener('input', e => this.filter(e.target.value));
    document.getElementById('modal-close').addEventListener('click', () => this.closeModal());
    document.getElementById('modal-overlay').addEventListener('click', e => { if (e.target === document.getElementById('modal-overlay')) this.closeModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') this.closeModal(); });
    document.getElementById('modal-enroll-btn').addEventListener('click', () => { if (this.modalStudentId) { document.getElementById('enroll-student-id').value = this.modalStudentId; Enroll.lookupStudent(this.modalStudentId); this.closeModal(); Router.navigate('enroll'); } });
    document.getElementById('modal-delete-btn').addEventListener('click', () => { if (this.modalStudentId) this.deleteStudent(this.modalStudentId); });
    document.getElementById('modal-edit-btn').addEventListener('click', () => this.enterEditMode());
    document.getElementById('modal-cancel-btn').addEventListener('click', () => this.cancelEdit());
    document.getElementById('modal-save-btn').addEventListener('click', () => this.saveEdit());
    document.getElementById('edit-photo-btn').addEventListener('click', () => document.getElementById('edit-photo-input').click());
    document.getElementById('edit-photo-input').addEventListener('change', function() {
      const file = this.files && this.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = e => {
        const img = document.getElementById('edit-avatar');
        img.style.backgroundImage = `url(${e.target.result})`;
        img.style.backgroundSize = 'cover';
        img.style.backgroundPosition = 'center';
        img.textContent = '';
      };
      reader.readAsDataURL(file);
    });
  },
  async load() {
    const grid = document.getElementById('student-grid'); const loading = document.getElementById('students-loading'); const empty = document.getElementById('students-empty');
    grid.querySelectorAll('.student-card').forEach(c => c.remove());
    loading.classList.remove('hidden'); empty.classList.add('hidden');
    try {
      const data = await API.get('/students/');
      this.all = Array.isArray(data) ? data : (data.results || []);
      this.filtered = [...this.all];
      this.updateStats(); this.render();
    } catch (err) { Toast.show('Failed to load students: ' + err.message, 'error'); }
    finally { loading.classList.add('hidden'); }
  },
  updateStats() {
    document.getElementById('stat-total').textContent = this.all.length;
    document.getElementById('stat-enrolled').textContent = this.all.filter(s => s.status === 'APPROVED').length;
    document.getElementById('stat-pending').textContent = this.all.filter(s => s.status !== 'APPROVED').length;
  },
  filter(query) { const q = query.toLowerCase().trim(); this.filtered = q ? this.all.filter(s => (s.full_name||'').toLowerCase().includes(q) || (s.registration_no||'').toLowerCase().includes(q) || (s.college_name||'').toLowerCase().includes(q)) : [...this.all]; this.render(); },
  render() {
    const grid = document.getElementById('student-grid'); const empty = document.getElementById('students-empty');
    grid.querySelectorAll('.student-card').forEach(c => c.remove());
    if (this.filtered.length === 0) { empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    this.filtered.forEach(s => { grid.appendChild(this.buildCard(s)); });
  },
  buildCard(s) {
    const initials = (s.full_name || '?').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
    const isApproved = s.status === 'APPROVED';
    const card = document.createElement('article');
    card.className = 'student-card'; card.setAttribute('tabindex', '0'); card.setAttribute('role', 'button');
    card.innerHTML = `<div class="card-top"><div class="card-avatar">${initials}</div><div><div class="card-name">${escHtml(s.full_name||'—')}</div><div class="card-reg">${escHtml(s.registration_no||'—')}</div></div><span class="card-badge ${isApproved?'enrolled':'pending'}">${isApproved?'Approved':s.status||'Pending'}</span></div><div class="card-info">${s.college_name?`<div class="card-info-item"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M10.394 2.08a1 1 0 00-.788 0l-7 3a1 1 0 000 1.84L5.25 8.051a.999.999 0 01.356-.257l4-1.714a1 1 0 11.788 1.838l-2.727 1.17 1.94.831a1 1 0 00.787 0l7-3a1 1 0 000-1.838l-7-3z"/></svg>${escHtml(s.college_name)}</div>`:''}${s.email?`<div class="card-info-item"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884zM18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z"/></svg>${escHtml(s.email)}</div>`:''}</div>`;
    const open = () => this.openModal(s);
    card.addEventListener('click', open); card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') open(); });
    return card;
  },
  openModal(s) {
    this.modalStudentId = s.student_id;
    this._studentData = null;
    document.getElementById('modal-view').classList.remove('hidden');
    document.getElementById('modal-edit').classList.add('hidden');

    // Show initial data from list
    this._populateView(s);
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('modal-close').focus();

    // Fetch full details
    this._fetchDetail(s.student_id);
  },

  _populateView(s) {
    const initials = (s.full_name||'?').split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2);
    document.getElementById('modal-avatar').textContent = initials;
    document.getElementById('modal-photo-img').classList.add('hidden');
    document.getElementById('modal-photo-img').src = '';
    document.getElementById('modal-title').textContent = s.full_name||'—';
    document.getElementById('modal-reg').textContent = s.registration_no||'—';
    document.getElementById('modal-meta').textContent = s.college_name ? `College: ${s.college_name}` : '';
    document.getElementById('md-dob').textContent = s.date_of_birth||'—';
    document.getElementById('md-gender').textContent = s.gender||'—';
    document.getElementById('md-college').textContent = s.college_name||'—';
    document.getElementById('md-email').textContent = s.email||'—';
    document.getElementById('md-phone').textContent = s.phone||'—';
    document.getElementById('md-created').textContent = s.created_at ? new Date(s.created_at).toLocaleDateString() : '—';
    document.getElementById('md-id').textContent = s.student_id;
    document.getElementById('md-consent').textContent = s.consent_signed ? 'Signed' : 'Not signed';
    document.getElementById('modal-badge').innerHTML = `<span class="card-badge ${s.status==='APPROVED'?'enrolled':'pending'}">${s.status||'—'}</span>`;
    // Reset fingerprint, exams & docs
    document.getElementById('modal-fingerprint-empty').classList.remove('hidden');
    document.getElementById('modal-fingerprint-loaded').classList.add('hidden');
    document.getElementById('modal-exams-empty').classList.remove('hidden');
    document.getElementById('modal-exams-list').classList.add('hidden');
    document.getElementById('modal-documents-empty').classList.remove('hidden');
    document.getElementById('modal-documents-list').classList.add('hidden');
  },

  async _fetchDetail(id) {
    try {
      const data = await API.get(`/students/${id}/`);
      this._studentData = data;

      // Photo
      if (data.photo_base64) {
        document.getElementById('modal-photo-img').src = data.photo_base64;
        document.getElementById('modal-photo-img').classList.remove('hidden');
        document.getElementById('modal-avatar').classList.add('hidden');
      }

      // Fingerprint
      if (data.fingerprint_image_base64) {
        document.getElementById('modal-fingerprint-img').src = data.fingerprint_image_base64;
        document.getElementById('modal-fingerprint-empty').classList.add('hidden');
        document.getElementById('modal-fingerprint-loaded').classList.remove('hidden');
      }

      // Enrolled exams
      const exams = data.enrolled_exams || [];
      if (exams.length > 0) {
        document.getElementById('modal-exams-empty').classList.add('hidden');
        const list = document.getElementById('modal-exams-list');
        list.classList.remove('hidden');
        list.innerHTML = exams.map(e => {
          return `<div class="doc-item">
            <svg class="doc-item-icon" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z"/></svg>
            <div class="doc-item-info"><div class="doc-item-name">${escHtml(e.subject_name)}</div><div class="doc-item-meta">${e.date} at ${e.start_time}</div></div>
          </div>`;
        }).join('');
      }

      // Documents
      const docs = data.documents || [];
      if (docs.length > 0) {
        document.getElementById('modal-documents-empty').classList.add('hidden');
        const list = document.getElementById('modal-documents-list');
        list.classList.remove('hidden');
        list.innerHTML = docs.map(d => {
          const icon = d.document_type === 'PDF' ? 'pdf' : 'doc';
          const size = d.file_size ? `${(d.file_size / 1024).toFixed(1)} KB` : '';
          return `<div class="doc-item">
            <svg class="doc-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>
            <div class="doc-item-info"><div class="doc-item-name">${escHtml(d.file_name || `Document #${d.doc_id}`)}</div><div class="doc-item-meta">${escHtml(d.document_type)}${size ? ' · ' + size : ''} · ${d.uploaded_at ? new Date(d.uploaded_at).toLocaleDateString() : ''}</div></div>
            <a href="/api/documents/${d.doc_id}/download/" class="btn btn-ghost" style="font-size:.8rem;padding:6px 12px" download>Download</a>
          </div>`;
        }).join('');
      }
    } catch { /* detail fetch failed, keep basic info */ }
  },

  closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.getElementById('modal-view').classList.remove('hidden');
    document.getElementById('modal-edit').classList.add('hidden');
    this.modalStudentId = null;
    this._studentData = null;
  },

  async enterEditMode() {
    const s = this._studentData;
    if (!s) { Toast.show('Still loading data...', 'info'); return; }
    const initials = (s.full_name||'?').split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2);
    document.getElementById('edit-avatar').textContent = initials;
    document.getElementById('edit-avatar').style.backgroundImage = '';
    document.getElementById('edit-full-name').value = s.full_name||'';
    document.getElementById('edit-reg-no').value = s.registration_no||'';
    document.getElementById('edit-dob').value = s.date_of_birth||'';
    document.getElementById('edit-gender').value = s.gender||'';
    document.getElementById('edit-college').value = s.college_name||'';
    document.getElementById('edit-email').value = s.email||'';
    document.getElementById('edit-phone').value = s.phone||'';
    document.getElementById('edit-special-needs').value = s.special_needs ? 'true' : 'false';
    document.getElementById('edit-special-notes').value = s.special_needs_notes||'';
    document.getElementById('edit-badge').innerHTML = `<span class="card-badge ${s.status==='APPROVED'?'enrolled':'pending'}">${s.status||'—'}</span>`;
    if (s.photo_base64) {
      const img = document.getElementById('edit-avatar');
      img.style.backgroundImage = `url(${s.photo_base64})`;
      img.style.backgroundSize = 'cover';
      img.style.backgroundPosition = 'center';
      img.textContent = '';
    }
    // Load exams and pre-select enrolled ones
    const enrolledIds = new Set((s.enrolled_exams || []).map(e => e.exam_id));
    const examSel = document.getElementById('edit-exam-ids');
    if (examSel) {
      try {
        const exams = await API.get('/exams/');
        examSel.innerHTML = exams.map(e => {
          const selected = enrolledIds.has(e.exam_id) ? ' selected' : '';
          return `<option value="${e.exam_id}"${selected}>${escHtml(e.subject_name||'')} — ${e.date||''}</option>`;
        }).join('');
      } catch { examSel.innerHTML = ''; }
    }
    document.getElementById('modal-view').classList.add('hidden');
    document.getElementById('modal-edit').classList.remove('hidden');
  },

  cancelEdit() {
    document.getElementById('modal-view').classList.remove('hidden');
    document.getElementById('modal-edit').classList.add('hidden');
  },

  async saveEdit() {
    const btn = document.getElementById('modal-save-btn');
    btn.classList.add('loading'); btn.disabled = true;
    try {
      const fd = new FormData();
      fd.append('full_name', document.getElementById('edit-full-name').value);
      fd.append('registration_no', document.getElementById('edit-reg-no').value);
      fd.append('date_of_birth', document.getElementById('edit-dob').value);
      fd.append('gender', document.getElementById('edit-gender').value);
      fd.append('college_name', document.getElementById('edit-college').value);
      fd.append('email', document.getElementById('edit-email').value);
      fd.append('phone', document.getElementById('edit-phone').value);
      fd.append('special_needs', document.getElementById('edit-special-needs').value === 'true');
      fd.append('special_needs_notes', document.getElementById('edit-special-notes').value);
      // Append exam_ids (always send — empty string means clear all)
      const examSelect = document.getElementById('edit-exam-ids');
      const selectedExamIds = Array.from(examSelect.selectedOptions).map(o => o.value);
      if (selectedExamIds.length > 0) {
        selectedExamIds.forEach(id => fd.append('exam_ids', id));
      } else {
        fd.append('exam_ids', ''); // send empty to clear all enrollments
      }
      const photoInput = document.getElementById('edit-photo-input');
      if (photoInput.files && photoInput.files[0]) {
        fd.append('photo', photoInput.files[0]);
      }
      await API.put(`/students/${this.modalStudentId}/`, fd);
      Toast.show('Student details updated', 'success');
      this.cancelEdit();
      this.load(); // refresh the list
      this._fetchDetail(this.modalStudentId); // refresh detail data
    } catch (err) { Toast.show('Update failed: ' + err.message, 'error'); }
    finally { btn.classList.remove('loading'); btn.disabled = false; }
  },

  async deleteStudent(id) { if (!confirm(`Delete student #${id}?`)) return; try { await API.del(`/students/${id}/`); Toast.show('Deleted', 'success'); this.closeModal(); this.load(); } catch (err) { Toast.show('Delete failed: ' + err.message, 'error'); } },
};

/* ═══════════════════════════════════════════
   NEW: ADMIN REGISTRATION QUEUE
   ═══════════════════════════════════════════ */
const Admin = {
  currentStatus: '',
  init() {
    document.getElementById('admin-refresh-btn').addEventListener('click', () => this.load());
    document.querySelectorAll('#admin-filter-bar .filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#admin-filter-bar .filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.currentStatus = btn.dataset.status;
        this.load();
      });
    });
  },
  async load() {
    const tbody = document.getElementById('admin-table-body'); const loading = document.getElementById('admin-loading'); const empty = document.getElementById('admin-empty');
    tbody.innerHTML = ''; loading.classList.remove('hidden'); empty.classList.add('hidden');
    try {
      let url = '/admin/registrations/';
      if (this.currentStatus) url += `?status=${this.currentStatus}`;
      const data = await API.get(url);
      if (data.length === 0) { empty.classList.remove('hidden'); return; }
      data.forEach(s => { tbody.appendChild(this.buildRow(s)); });
    } catch (err) { Toast.show('Failed to load: ' + err.message, 'error'); }
    finally { loading.classList.add('hidden'); }
  },
  buildRow(s) {
    const tr = document.createElement('tr');
    const statusClass = (s.status||'').toLowerCase().replace(/_/g,'_');
    tr.innerHTML = `
      <td>${s.student_id}</td>
      <td><strong>${escHtml(s.full_name)}</strong></td>
      <td>${escHtml(s.registration_no||'—')}</td>
      <td>${escHtml(s.email||'—')}</td>
      <td><span class="status-badge ${statusClass}">${s.status||'—'}</span></td>
      <td>${s.document_count||0}</td>
      <td>${s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}</td>
      <td><div class="btn-group">${this.actionBtns(s)}</div></td>`;
    return tr;
  },
  actionBtns(s) {
    if (s.status === 'SUBMITTED' || s.status === 'UNDER_REVIEW' || s.status === 'REUPLOAD_REQUESTED') {
      return `<button class="action-btn approve" data-action="approve" data-id="${s.student_id}">Approve</button>
              <button class="action-btn reject" data-action="reject" data-id="${s.student_id}">Reject</button>`;
    }
    return `<span style="color:var(--text-3);font-size:.75rem">${s.status === 'APPROVED' ? 'Completed' : 'Closed'}</span>`;
  },
  handleClick(e) {
    const btn = e.target.closest('.action-btn');
    if (!btn) return;
    const id = btn.dataset.id; const action = btn.dataset.action;
    if (action === 'approve') this.approve(id);
    else if (action === 'reject') this.reject(id);
  },
  async approve(id) {
    try { await API.post(`/admin/registrations/${id}/approve/`); Toast.show(`Student #${id} approved`, 'success'); this.load(); }
    catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async reject(id) {
    const reason = prompt('Rejection reason (optional):');
    try { await API.post(`/admin/registrations/${id}/reject/`, { reason: reason||'' }); Toast.show(`Student #${id} rejected`, 'info'); this.load(); }
    catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
};

/* ═══════════════════════════════════════════
   NEW: EXAM MANAGER
   ═══════════════════════════════════════════ */
const ExamManager = {
  _hallsData: [],

  init() {
    // Tabs
    document.querySelectorAll('#exams-tabs .tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#exams-tabs .tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel[id^="tab-"]').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
        if (btn.dataset.tab === 'subjects') this.loadSubjects();
        if (btn.dataset.tab === 'centers') this.loadCenters();
        if (btn.dataset.tab === 'exams') this.loadExams();
      });
    });
    // Subject
    document.getElementById('subject-add-btn').addEventListener('click', () => this.addSubject());
    // Center
    document.getElementById('center-add-btn').addEventListener('click', () => this.addCenter());
    // Hall
    document.getElementById('hall-add-btn').addEventListener('click', () => this.addHall());
    // Exam
    document.getElementById('exam-form').addEventListener('submit', e => { e.preventDefault(); this.saveExam(); });
    document.getElementById('exam-refresh-btn').addEventListener('click', () => this.loadExams());
    // Filter halls when center changes
    const centerSel = document.getElementById('exam-center');
    if (centerSel) {
      centerSel.addEventListener('change', () => this.filterHallsByCenter());
    }
  },
  load() {
    // Populate dropdowns across pages
    this.loadSubjects();
  },

  filterHallsByCenter() {
    const centerId = parseInt(document.getElementById('exam-center').value);
    const hallSel = document.getElementById('exam-halls');
    if (!hallSel) return;
    if (!centerId) {
      hallSel.innerHTML = '';
      return;
    }
    hallSel.innerHTML = this._hallsData
      .filter(h => h.center === centerId || h.center_id === centerId)
      .map(h => `<option value="${h.hall_id}">${escHtml(h.name)}</option>`)
      .join('');
  },

  /* ─── Subjects ─── */
  async loadSubjects() {
    const tbody = document.getElementById('subjects-table-body'); const loading = document.getElementById('subjects-loading');
    try {
      const data = await API.get('/subjects/');
      tbody.innerHTML = data.map(s => `<tr><td>${s.subject_id}</td><td>${escHtml(s.code)}</td><td>${escHtml(s.name)}</td><td><button class="action-btn" data-del-subject="${s.subject_id}">Delete</button></td></tr>`).join('');
      tbody.querySelectorAll('[data-del-subject]').forEach(btn => btn.addEventListener('click', () => this.delSubject(btn.dataset.delSubject)));
      // Populate selects
      this.populateSubjectSelects(data);
    } catch (err) { Toast.show('Failed to load subjects: ' + err.message, 'error'); }
  },
  populateSubjectSelects(subjects) {
    const selects = ['exam-subject'];
    selects.forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const val = sel.value;
      sel.innerHTML = '<option value="">— Select —</option>' + subjects.map(s => `<option value="${s.subject_id}">${escHtml(s.code)} - ${escHtml(s.name)}</option>`).join('');
      if (val) sel.value = val;
    });
  },
  async addSubject() {
    const code = document.getElementById('subject-code').value.trim(); const name = document.getElementById('subject-name').value.trim();
    if (!code || !name) { Toast.show('Code and name required', 'error'); return; }
    try { await API.post('/subjects/', { code, name }); Toast.show('Subject added', 'success'); document.getElementById('subject-code').value = ''; document.getElementById('subject-name').value = ''; this.loadSubjects(); }
    catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async delSubject(id) { if (!confirm('Delete this subject?')) return; try { await API.del(`/subjects/${id}/`); Toast.show('Deleted', 'success'); this.loadSubjects(); } catch (err) { Toast.show('Error: ' + err.message, 'error'); } },

  /* ─── Centers ─── */
  async loadCenters() {
    try {
      const data = await API.get('/centers/');
      document.getElementById('centers-table-body').innerHTML = data.map(c => `<tr><td>${c.center_id}</td><td>${escHtml(c.name)}</td><td>${escHtml(c.address||'')}</td><td><button class="action-btn" data-del-center="${c.center_id}">Delete</button></td></tr>`).join('');
      document.querySelectorAll('[data-del-center]').forEach(btn => btn.addEventListener('click', () => this.delCenter(btn.dataset.delCenter)));
      // Populate selects
      const selects = ['hall-center-select', 'exam-center'];
      selects.forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        sel.innerHTML = '<option value="">— Select —</option>' + data.map(c => `<option value="${c.center_id}">${escHtml(c.name)}</option>`).join('');
      });
      this.loadHalls();
    } catch (err) { Toast.show('Failed to load centers: ' + err.message, 'error'); }
  },
  async addCenter() {
    const name = document.getElementById('center-name').value.trim(); const address = document.getElementById('center-address').value.trim();
    if (!name) { Toast.show('Center name required', 'error'); return; }
    try { await API.post('/centers/', { name, address }); Toast.show('Center added', 'success'); document.getElementById('center-name').value = ''; document.getElementById('center-address').value = ''; this.loadCenters(); }
    catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async delCenter(id) { if (!confirm('Delete this center?')) return; try { await API.del(`/centers/${id}/`); Toast.show('Deleted', 'success'); this.loadCenters(); } catch (err) { Toast.show('Error: ' + err.message, 'error'); } },

  /* ─── Halls ─── */
  async loadHalls() {
    try {
      const data = await API.get('/halls/');
      this._hallsData = data;
      document.getElementById('halls-table-body').innerHTML = data.map(h => `<tr><td>${h.hall_id}</td><td>${escHtml(h.name)}</td><td>${escHtml(h.center_name||'')}</td><td>${h.rows}</td><td>${h.columns}</td><td>${h.total_capacity}</td><td><button class="action-btn" data-del-hall="${h.hall_id}">Delete</button></td></tr>`).join('');
      document.querySelectorAll('[data-del-hall]').forEach(btn => btn.addEventListener('click', () => this.delHall(btn.dataset.delHall)));
      // Populate exam hall select based on current center selection
      this.filterHallsByCenter();
    } catch (err) { Toast.show('Failed to load halls: ' + err.message, 'error'); }
  },
  async addHall() {
    const center_id = document.getElementById('hall-center-select').value;
    const name = document.getElementById('hall-name').value.trim();
    const rows = parseInt(document.getElementById('hall-rows').value) || 10;
    const columns = parseInt(document.getElementById('hall-cols').value) || 10;
    if (!center_id || !name) { Toast.show('Center and name required', 'error'); return; }
    try { await API.post('/halls/', { center: parseInt(center_id), name, rows, columns }); Toast.show('Hall added', 'success'); document.getElementById('hall-name').value = ''; this.loadHalls(); }
    catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async delHall(id) { if (!confirm('Delete this hall?')) return; try { await API.del(`/halls/${id}/`); Toast.show('Deleted', 'success'); this.loadHalls(); } catch (err) { Toast.show('Error: ' + err.message, 'error'); } },

  /* ─── Exams ─── */
  async loadExams() {
    try {
      // Refresh dropdowns for form
      await this.loadSubjects();
      const centers = await API.get('/centers/');
      const centerSel = document.getElementById('exam-center');
      if (centerSel) { centerSel.innerHTML = '<option value="">— Select —</option>' + centers.map(c => `<option value="${c.center_id}">${escHtml(c.name)}</option>`).join(''); }
      // Ensure halls data is loaded for the center-specific filter
      if (this._hallsData.length === 0) {
        await this.loadHalls();
      } else {
        this.filterHallsByCenter();
      }

      const data = await API.get('/exams/');
      const tbody = document.getElementById('exams-table-body');
      tbody.innerHTML = data.map(e => `<tr>
        <td>${e.exam_id}</td><td>${escHtml(e.subject_name||'')}</td><td>${e.date||''}</td>
        <td>${e.start_time||''}</td><td>${escHtml(e.center_name||'')}</td>
        <td>${e.enrolled_count||0}</td><td>${e.hall_count||0}</td>
        <td><span class="status-badge ${e.is_locked?'locked':''}">${e.is_locked?'Locked':'Open'}</span></td>
        <td>${e.is_locked?'':`<button class="action-btn" data-lock-exam="${e.exam_id}">Lock</button>`}</td>
      </tr>`).join('');
      tbody.querySelectorAll('[data-lock-exam]').forEach(btn => btn.addEventListener('click', () => this.lockExam(btn.dataset.lockExam)));

      // Populate exam selects for other pages
      SeatManager.populateExamSelects(data);
      ReportManager.populateExamSelects(data);
    } catch (err) { Toast.show('Failed to load exams: ' + err.message, 'error'); }
  },
  async saveExam() {
    const data = {
      subject: parseInt(document.getElementById('exam-subject').value),
      date: document.getElementById('exam-date').value,
      start_time: document.getElementById('exam-time').value,
      duration_minutes: parseInt(document.getElementById('exam-duration').value) || 180,
      center: parseInt(document.getElementById('exam-center').value),
      cutoff_date: document.getElementById('exam-cutoff').value || null,
    };
    const hallSelect = document.getElementById('exam-halls');
    data.hall_ids = Array.from(hallSelect.selectedOptions).map(o => parseInt(o.value));
    if (!data.subject || !data.date || !data.start_time || !data.center) { Toast.show('Fill required fields', 'error'); return; }
    try { await API.post('/exams/', data); Toast.show('Exam created', 'success'); document.getElementById('exam-form').reset(); this.loadExams(); }
    catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async lockExam(id) { if (!confirm('Lock exam #' + id + '?')) return; try { await API.post(`/exams/${id}/lock/`); Toast.show('Exam locked', 'success'); this.loadExams(); } catch (err) { Toast.show('Error: ' + err.message, 'error'); } },
};

/* ═══════════════════════════════════════════
   NEW: SEAT MANAGER
   ═══════════════════════════════════════════ */
const SeatManager = {
  init() {
    document.getElementById('seats-generate-btn').addEventListener('click', () => this.generate());
    document.getElementById('seats-view-btn').addEventListener('click', () => this.view());
    document.getElementById('seats-view-exam').addEventListener('change', () => this.loadHallsForView());
  },
  load() {
    // Populate exam selects
    API.get('/exams/').then(data => this.populateExamSelects(data)).catch(() => {});
  },
  populateExamSelects(exams) {
    const selects = ['seats-exam-select', 'seats-view-exam'];
    selects.forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const val = sel.value;
      sel.innerHTML = '<option value="">— Select Exam —</option>' + exams.map(e => `<option value="${e.exam_id}">${escHtml(e.subject_name||'')} - ${e.date||''}</option>`).join('');
      if (val) sel.value = val;
    });
  },
  async loadHallsForView() {
    const examId = parseInt(document.getElementById('seats-view-exam').value);
    const hallSel = document.getElementById('seats-view-hall');
    if (!examId) { hallSel.innerHTML = '<option value="">All Halls</option>'; return; }
    try {
      const exam = await API.get(`/exams/${examId}/`);
      const halls = exam.halls_detail || [];
      hallSel.innerHTML = '<option value="">All Halls</option>' +
        halls.map(h => `<option value="${h.hall_id}">${escHtml(h.name)}</option>`).join('');
    } catch {
      hallSel.innerHTML = '<option value="">All Halls</option>';
    }
  },
  async generate() {
    const exam_id = parseInt(document.getElementById('seats-exam-select').value);
    if (!exam_id) { Toast.show('Select an exam', 'error'); return; }
    const btn = document.getElementById('seats-generate-btn'); btn.classList.add('loading'); btn.disabled = true;
    try {
      const data = await API.post('/exams/generate-seat-map/', { exam_id, reserve_buffer: document.getElementById('seats-buffer').checked });
      const resultDiv = document.getElementById('seats-result'); resultDiv.classList.remove('hidden');
      let html = `<div class="result-badge success" style="margin-bottom:12px"><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/></svg><span>${data.message||'Seat map generated'}</span></div>`;
      if (data.warnings && data.warnings.length) html += data.warnings.map(w => `<div style="color:var(--amber);font-size:.8rem;padding:6px 0">⚠️ ${escHtml(w)}</div>`).join('');
      if (data.halls) html += '<div style="margin-top:10px;font-size:.82rem">' + data.halls.map(h => `<div class="analytics-stat"><span class="label">${escHtml(h.hall_name)}</span><span class="value">${h.assigned} seats</span></div>`).join('') + '</div>';
      resultDiv.innerHTML = html;
      Toast.show(data.message, 'success');
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
    finally { btn.classList.remove('loading'); btn.disabled = false; }
  },
  _renderHall(hall) {
    const { name: hname, rows, columns, assignments } = hall;
    const rowLabels = [];
    for (let i = 0; i < rows; i++) rowLabels.push(String.fromCharCode(65 + i));
    const takenSet = new Set(assignments.map(a => `${a.row},${a.col}`));
    const colMid = Math.floor(columns / 2);
    let taken = 0, free = 0;

    // Build a lookup by (row,col) for quick access
    const assignMap = {};
    assignments.forEach(a => { assignMap[`${a.row},${a.col}`] = a; });

    let html = `<div class="hall-layout" style="margin-bottom:24px"><div class="hall-layout-title">${escHtml(hname)}</div>`;
    html += `<div class="room-box"><div class="board-row">`;
    html += `<div class="door-wrap"><div class="door"><div class="door-arc"></div></div><span class="door-label">DOOR</span></div>`;
    html += `<div class="board">BOARD / FRONT OF HALL</div></div>`;

    // Column numbers
    html += '<div class="col-nums">';
    for (let c = 0; c < columns; c++) {
      if (c === colMid) html += '<div class="col-num aisle-gap"></div>';
      html += `<div class="col-num">${c + 1}</div>`;
    }
    html += '</div>';

    // Seat rows
    html += '<div class="rows">';
    for (let r = 0; r < rows; r++) {
      html += `<div class="seat-row"><div class="row-label">${rowLabels[r]}</div><div class="seats">`;
      for (let c = 0; c < columns; c++) {
        if (c === colMid) html += '<div class="aisle"></div>';
        const key = `${r},${c}`;
        const assn = assignMap[key] || null;
        const isTaken = !!assn;
        const state = isTaken ? 'taken' : 'free';
        if (isTaken) taken++; else free++;
        const seatLabel = escHtml(assn ? assn.seat_label : `${rowLabels[r]}${c + 1}`);
        const regNo = assn ? escHtml(assn.registration_no) : '';
        const sid = assn ? assn.student_id : '';
        const sname = assn ? escHtml(assn.student_name) : '';
        html += `<div class="seat ${state}" data-sid="${sid}" data-student="${sname}" data-reg="${regNo}" data-seat="${rowLabels[r]}${c + 1}">`;
        if (isTaken) {
          html += `<span class="seat-reg">${regNo}</span><span class="seat-num">${seatLabel}</span>`;
        } else {
          html += `<span class="seat-num seat-num-free">${seatLabel}</span>`;
        }
        html += `</div>`;
      }
      html += '</div></div>';
    }
    html += '</div>';

    // Stats
    html += `<div class="hall-stats"><span class="stat-pill stat-taken">${taken} Taken</span><span class="stat-pill stat-free">${free} Unoccupied</span></div>`;

    // Legend
    html += '<div class="legend">';
    html += `<div class="legend-item"><div class="legend-dot" style="background:var(--taken)"></div>Taken</div>`;
    html += `<div class="legend-item"><div class="legend-dot" style="background:var(--free)"></div>Unoccupied</div>`;
    html += '</div></div></div>';

    return html;
  },

  async view() {
    const exam_id = parseInt(document.getElementById('seats-view-exam').value);
    if (!exam_id) { Toast.show('Select an exam', 'error'); return; }
    const hall_id = parseInt(document.getElementById('seats-view-hall').value) || '';
    try {
      const data = await API.get(`/exams/${exam_id}/seat-assignments/${hall_id ? `?hall_id=${hall_id}` : ''}`);
      const resultDiv = document.getElementById('seats-view-result'); resultDiv.classList.remove('hidden');
      const halls = data.halls || [];
      if (halls.length === 0) { resultDiv.innerHTML = '<p style="color:var(--text-3)">No seat assignments found.</p>'; return; }

      let html = `<div style="margin-bottom:12px;font-size:.82rem;color:var(--text-3)">${escHtml(data.subject)} — ${data.date} ${data.start_time}</div>`;
      halls.forEach(h => { html += this._renderHall(h); });
      resultDiv.innerHTML = html;

      // Click popup on taken seats
      const popup = document.getElementById('seat-popup');
      if (!popup) { const p = document.createElement('div'); p.id = 'seat-popup'; p.className = 'seat-popup hidden'; document.body.appendChild(p); }
      resultDiv.querySelectorAll('.seat.taken').forEach(el => {
        el.addEventListener('click', e => {
          e.stopPropagation();
          const pop = document.getElementById('seat-popup');
          const sid = parseInt(el.dataset.sid);
          const name = el.dataset.student;
          const reg = el.dataset.reg;
          const seat = el.dataset.seat;
          pop.innerHTML = `<div class="seat-popup-header">
            <div class="seat-popup-avatar">${(name||'?').split(' ').map(w=>w[0]).filter(Boolean).slice(0,2).join('').toUpperCase()}</div>
            <div><div class="seat-popup-name">${escHtml(name)}</div><div class="seat-popup-reg">${escHtml(reg)}</div></div>
          </div>
          <div class="seat-popup-meta">Seat <strong>${seat}</strong></div>
          <button class="btn btn-primary btn-full seat-popup-view">View Full Details</button>
          <button class="btn btn-ghost btn-full seat-popup-close">Close</button>`;
          // Position near click
          let left = e.clientX + 12, top = e.clientY - 10;
          if (left + 240 > window.innerWidth) left = e.clientX - 250;
          if (top < 10) top = e.clientY + 10;
          pop.style.left = left + 'px'; pop.style.top = top + 'px';
          pop.classList.remove('hidden');
          // View details
          pop.querySelector('.seat-popup-view').addEventListener('click', () => {
            pop.classList.add('hidden');
            if (window.Students) window.Students.openModal({ student_id: sid });
          });
          pop.querySelector('.seat-popup-close').addEventListener('click', () => pop.classList.add('hidden'));
        });
      });
      // Click elsewhere closes popup
      document.addEventListener('click', e => {
        const pop = document.getElementById('seat-popup');
        if (pop && !pop.classList.contains('hidden') && !pop.contains(e.target) && !e.target.closest('.seat.taken')) {
          pop.classList.add('hidden');
        }
      }, { once: false });
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
};

/* ═══════════════════════════════════════════
   EXAM SESSIONS
   ═══════════════════════════════════════════ */
const SessionsManager = {
  init() {
    document.getElementById('session-start-btn').addEventListener('click', () => this.startSession());
    document.getElementById('session-history-btn').addEventListener('click', () => this.loadHistory());
    document.getElementById('session-history-date').valueAsDate = new Date();
  },
  load() {
    this.loadExams();
    this.loadActive();
  },
  async loadExams() {
    try {
      const data = await API.get('/exams/');
      const sel = document.getElementById('session-exam-select');
      sel.innerHTML = '<option value="">— Select Exam —</option>' + (data || []).map(e =>
        `<option value="${e.exam_id}">${escHtml(e.subject_name||'')} — ${e.date||''}</option>`
      ).join('');
    } catch { /* ignore */ }
  },
  async loadActive() {
    try {
      const data = await API.get('/exam-sessions/active/');
      const card = document.getElementById('session-active-content');
      const outer = document.getElementById('session-active-card');
      if (!data.is_active || !data.session_id) {
        card.innerHTML = '<p style="color:var(--text-3);font-size:.9rem">No active session</p>';
        outer.style.borderLeftColor = 'var(--border)';
        return;
      }
      outer.style.borderLeftColor = 'var(--success)';
      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
          <div>
            <div style="font-size:1.1rem;font-weight:700">${escHtml(data.subject_name||data.exam_name)}</div>
            <div style="font-size:.85rem;color:var(--text-2);margin-top:4px">
              Date: ${data.exam_date||'—'} &middot; Started by: ${escHtml(data.started_by||'—')} &middot;
              Entries: <strong>${data.entry_count||0}</strong>
            </div>
          </div>
          <button class="btn btn-danger-outline" id="session-end-btn">End Session</button>
        </div>`;
      document.getElementById('session-end-btn').addEventListener('click', () => this.endSession(data.session_id));
    } catch { /* ignore */ }
  },
  async startSession() {
    const exam_id = document.getElementById('session-exam-select').value;
    const started_by = document.getElementById('session-started-by').value.trim();
    if (!exam_id) { Toast.show('Select an exam', 'error'); return; }
    if (!started_by) { Toast.show('Enter your name', 'error'); return; }
    try {
      const data = await API.post('/exam-sessions/start/', { exam_id: parseInt(exam_id), started_by });
      Toast.show('Session started!', 'success');
      this.loadActive();
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async endSession(session_id) {
    if (!confirm('End this active session?')) return;
    try {
      await API.post(`/exam-sessions/${session_id}/end/`);
      Toast.show('Session ended', 'success');
      this.loadActive();
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async loadHistory() {
    const date = document.getElementById('session-history-date').value;
    try {
      const qs = date ? `?date=${date}` : '';
      const data = await API.get(`/exam-sessions/${qs}`);
      const div = document.getElementById('session-history-result');
      if (!data || data.length === 0) {
        div.innerHTML = '<p style="color:var(--text-3);font-size:.85rem;margin-top:8px">No sessions found</p>';
        return;
      }
      div.innerHTML = `<table class="data-table"><thead><tr>
        <th>Exam</th><th>Date</th><th>Started By</th><th>Started</th><th>Ended</th><th>Status</th>
      </tr></thead><tbody>
        ${data.map(s => `<tr>
          <td>${escHtml(s.subject_name||s.exam_name)}</td>
          <td>${s.exam_date||'—'}</td>
          <td>${escHtml(s.started_by||'—')}</td>
          <td>${s.started_at ? new Date(s.started_at).toLocaleString() : '—'}</td>
          <td>${s.ended_at ? new Date(s.ended_at).toLocaleString() : '—'}</td>
          <td><span class="status-badge ${s.is_active ? 'granted' : ''}">${s.is_active ? 'Active' : 'Ended'}</span></td>
        </tr>`).join('')}
      </tbody></table>`;
    } catch { Toast.show('Failed to load history', 'error'); }
  },
};

/* ═══════════════════════════════════════════
   NEW: REPORTS & ANALYTICS
   ═══════════════════════════════════════════ */
const ReportManager = {
  init() {
    // Tabs
    document.querySelectorAll('#reports-tabs .tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#reports-tabs .tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('#tab-attendance, #tab-analytics').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
        if (btn.dataset.tab === 'analytics') this.loadAnalytics();
      });
    });
    // Attendance buttons
    document.getElementById('report-attendance-btn').addEventListener('click', () => this.viewAttendance());
    document.getElementById('report-csv-btn').addEventListener('click', () => this.downloadCsv());
    document.getElementById('absent-view-btn').addEventListener('click', () => this.viewAbsentees());
    document.getElementById('report-fallback-btn').addEventListener('click', () => this.viewFallback());
    document.getElementById('report-override-btn').addEventListener('click', () => this.viewOverrides());
  },
  load() {
    API.get('/exams/').then(data => this.populateExamSelects(data)).catch(() => {});
  },
  populateExamSelects(exams) {
    ['report-exam-select', 'absent-exam-select'].forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      sel.innerHTML = '<option value="">— Select Exam —</option>' + exams.map(e => `<option value="${e.exam_id}">${escHtml(e.subject_name||'')} - ${e.date||''}</option>`).join('');
    });
  },
  async viewAttendance() {
    const exam_id = document.getElementById('report-exam-select').value;
    if (!exam_id) { Toast.show('Select an exam', 'error'); return; }
    try {
      const data = await API.get(`/reports/exams/${exam_id}/attendance/`);
      const resultDiv = document.getElementById('report-attendance-result'); resultDiv.classList.remove('hidden');
      const records = data.records || [];
      resultDiv.innerHTML = `<div style="font-size:.82rem;margin-bottom:8px"><strong>${data.subject||''}</strong> — ${data.date||''} — Total enrolled: ${data.total_enrolled||0}</div>
        <table class="data-table"><thead><tr><th>Student</th><th>Reg No</th><th>State</th><th>Time</th><th>Method</th></tr></thead><tbody>
        ${records.map(r => `<tr><td>${escHtml(r.student_name)}</td><td>${escHtml(r.registration_no)}</td><td><span class="status-badge ${(r.entry_state||'').toLowerCase()}">${r.entry_state}</span></td><td>${r.entry_time?new Date(r.entry_time).toLocaleString():'—'}</td><td>${r.method||'—'}</td></tr>`).join('')}
        </tbody></table>`;
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async downloadCsv() {
    const exam_id = document.getElementById('report-exam-select').value;
    if (!exam_id) { Toast.show('Select an exam', 'error'); return; }
    window.open(`/api/reports/exams/${exam_id}/attendance/?export=csv`, '_blank');
  },
  async viewAbsentees() {
    const exam_id = document.getElementById('absent-exam-select').value;
    if (!exam_id) { Toast.show('Select an exam', 'error'); return; }
    try {
      const data = await API.get(`/reports/exams/${exam_id}/absentees/`);
      const resultDiv = document.getElementById('absent-result'); resultDiv.classList.remove('hidden');
      const list = data.absentees || [];
      resultDiv.innerHTML = `<div style="font-size:.82rem;margin-bottom:8px">Absentees: <strong>${data.absentee_count||0}</strong></div>
        <table class="data-table"><thead><tr><th>Student</th><th>Reg No</th><th>Email</th></tr></thead><tbody>
        ${list.map(s => `<tr><td>${escHtml(s.full_name)}</td><td>${escHtml(s.registration_no)}</td><td>${escHtml(s.email||'')}</td></tr>`).join('')}
        </tbody></table>`;
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async viewFallback() {
    try {
      const data = await API.get('/reports/fallback/');
      const resultDiv = document.getElementById('report-fallback-result'); resultDiv.classList.remove('hidden');
      const records = data.records || [];
      resultDiv.innerHTML = `<div style="font-size:.82rem;margin-bottom:8px">Fallback entries: <strong>${data.count||0}</strong></div>
        <table class="data-table"><thead><tr><th>Student</th><th>Exam</th><th>Time</th><th>Verified By</th></tr></thead><tbody>
        ${records.map(r => `<tr><td>${escHtml(r.student_name)}</td><td>${escHtml(r.exam_subject||'')}</td><td>${r.entry_time?new Date(r.entry_time).toLocaleString():'—'}</td><td>${escHtml(r.verified_by||'—')}</td></tr>`).join('')}
        </tbody></table>`;
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },
  async viewOverrides() {
    try {
      const data = await API.get('/reports/overrides/');
      const resultDiv = document.getElementById('report-override-result'); resultDiv.classList.remove('hidden');
      const overrides = data.overrides || [];
      resultDiv.innerHTML = `<div style="font-size:.82rem;margin-bottom:8px">Overrides: <strong>${data.count||0}</strong></div>
        <table class="data-table"><thead><tr><th>User</th><th>Target ID</th><th>Details</th><th>Timestamp</th></tr></thead><tbody>
        ${overrides.map(o => `<tr><td>${escHtml(o.user)}</td><td>${o.target_id||'—'}</td><td>${escHtml(JSON.stringify(o.details))}</td><td>${o.timestamp?new Date(o.timestamp).toLocaleString():'—'}</td></tr>`).join('')}
        </tbody></table>`;
    } catch (err) { Toast.show('Error: ' + err.message, 'error'); }
  },

  /* ─── Analytics ─── */
  async loadAnalytics() {
    this.loadAttendanceRate();
    this.loadHallOccupancy();
    this.loadFallbackRate();
    this.loadPeakTimes();
  },
  async loadAttendanceRate() {
    const container = document.getElementById('analytics-rate');
    try {
      const data = await API.get('/analytics/attendance-rate/');
      const sessions = data.sessions || [];
      container.innerHTML = '<div class="form-section-title">Attendance Rate</div>' + (sessions.length === 0 ? '<p style="color:var(--text-3);font-size:.82rem">No data</p>' :
        sessions.slice(0, 10).map(s => `<div class="analytics-stat"><span class="label">${escHtml(s.subject)} (${s.date||''})</span><span class="value">${s.attendance_rate}%</span></div><div class="analytics-bar-wrap"><div class="analytics-bar" style="width:${s.attendance_rate}%"></div></div>`).join(''));
    } catch { container.innerHTML = '<div class="form-section-title">Attendance Rate</div><p style="color:var(--red);font-size:.82rem">Failed to load</p>'; }
  },
  async loadHallOccupancy() {
    const container = document.getElementById('analytics-halls');
    try {
      const data = await API.get('/analytics/hall-occupancy/');
      const halls = data.halls || [];
      container.innerHTML = '<div class="form-section-title">Hall Occupancy</div>' + (halls.length === 0 ? '<p style="color:var(--text-3);font-size:.82rem">No data</p>' :
        halls.map(h => `<div class="analytics-stat"><span class="label">${escHtml(h.hall_name)} (${escHtml(h.center||'')})</span><span class="value">${h.assigned}/${h.capacity} (${h.utilisation}%)</span></div><div class="analytics-bar-wrap"><div class="analytics-bar" style="width:${h.utilisation}%"></div></div>`).join(''));
    } catch { container.innerHTML = '<div class="form-section-title">Hall Occupancy</div><p style="color:var(--red);font-size:.82rem">Failed to load</p>'; }
  },
  async loadFallbackRate() {
    const container = document.getElementById('analytics-fallback');
    try {
      const data = await API.get('/analytics/fallback-rate/');
      const centers = data.centers || [];
      container.innerHTML = '<div class="form-section-title">Fallback Rate by Center</div>' + (centers.length === 0 ? '<p style="color:var(--text-3);font-size:.82rem">No data</p>' :
        centers.map(c => `<div class="analytics-stat"><span class="label">${escHtml(c.center_name)}</span><span class="value">${c.fallback_rate}% (${c.fallback_entries}/${c.total_entries})</span></div>`).join(''));
    } catch { container.innerHTML = '<div class="form-section-title">Fallback Rate</div><p style="color:var(--red);font-size:.82rem">Failed to load</p>'; }
  },
  async loadPeakTimes() {
    const container = document.getElementById('analytics-peak');
    try {
      const data = await API.get('/analytics/peak-entry-times/');
      const histogram = data.histogram || [];
      const maxCount = Math.max(...histogram.map(h => h.count), 1);
      container.innerHTML = '<div class="form-section-title">Peak Entry Times</div>' + (histogram.length === 0 ? '<p style="color:var(--text-3);font-size:.82rem">Total entries: '+data.total_entries+'</p>' :
        `<p style="font-size:.78rem;color:var(--text-3);margin-bottom:10px">Total entries: ${data.total_entries}</p>` +
        histogram.map(h => `<div class="analytics-stat"><span class="label">${String(h.hour).padStart(2,'0')}:00</span><span class="value">${h.count}</span></div><div class="analytics-bar-wrap"><div class="analytics-bar" style="width:${(h.count/maxCount*100)}%"></div></div>`).join(''));
    } catch { container.innerHTML = '<div class="form-section-title">Peak Entry Times</div><p style="color:var(--red);font-size:.82rem">Failed to load</p>'; }
  },
};

/* ═══════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════ */
function escHtml(str) { return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function initMobileSidebar() {
  document.getElementById('hamburger').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
}

/* ═══════════════════════════════════════════
   BOOT
   ═══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  Toast.init();
  Register.init();
  Enroll.init();
  Students.init();
  Admin.init();
  ExamManager.init();
  SeatManager.init();
  SessionsManager.init();
  ReportManager.init();
  initMobileSidebar();

  // Delegate click events for admin table actions
  document.getElementById('admin-table-body').addEventListener('click', e => Admin.handleClick(e));

  // Wire nav buttons
  document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
    btn.addEventListener('click', () => Router.navigate(btn.dataset.page));
  });

  Router.navigate('register');
});
