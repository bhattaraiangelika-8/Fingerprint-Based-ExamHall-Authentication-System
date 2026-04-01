/**
 * Fingerprint upload — image preview and form submission
 */
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('fingerprint_image');
    const preview = document.getElementById('image-preview');
    const form = document.getElementById('fingerprint-form');

    if (!fileInput || !preview) return;

    // Image preview
    fileInput.addEventListener('change', function() {
        const file = this.files[0];
        if (!file) {
            preview.innerHTML = '<div class="placeholder"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg><div>Select an image to preview</div></div>';
            preview.classList.remove('has-image');
            return;
        }

        const reader = new FileReader();
        reader.onload = function(e) {
            preview.innerHTML = '<img src="' + e.target.result + '" alt="Fingerprint preview">';
            preview.classList.add('has-image');
        };
        reader.readAsDataURL(file);
    });

    if (!form) return;

    // Form submission
    form.addEventListener('submit', function(e) {
        e.preventDefault();

        const btn = document.getElementById('submit-btn');
        const btnText = btn.querySelector('.btn-text');
        const spinner = btn.querySelector('.spinner');
        btn.disabled = true;
        btnText.textContent = 'Enrolling...';
        spinner.style.display = 'inline-block';

        const formData = new FormData(form);

        fetch('/api/fingerprint/upload/', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': getCsrfToken()
            }
        })
        .then(function(response) {
            return response.json().then(function(data) {
                return { ok: response.ok, status: response.status, data: data };
            });
        })
        .then(function(result) {
            btn.disabled = false;
            btnText.textContent = 'Enroll Fingerprint';
            spinner.style.display = 'none';

            if (result.ok) {
                showToast('Fingerprint enrolled successfully!', 'success');
                showResult(result.data, true);
            } else {
                const data = result.data;
                showToast('Enrollment failed', 'error');
                showResult(data, false);
            }
        })
        .catch(function(err) {
            btn.disabled = false;
            btnText.textContent = 'Enroll Fingerprint';
            spinner.style.display = 'none';
            showToast('Network error: ' + err.message, 'error');
        });
    });
});

function showResult(data, success) {
    const card = document.getElementById('result-card');
    const content = document.getElementById('result-content');
    card.style.display = 'block';

    if (success) {
        let qualityHtml = '';
        if (data.quality) {
            qualityHtml = '<p><strong>Quality Score:</strong> ' + (data.quality.overall_score || 'N/A') +
                ' <span class="badge ' + (data.quality.is_acceptable ? 'badge-success' : 'badge-danger') + '">' +
                (data.quality.is_acceptable ? 'Acceptable' : 'Poor') + '</span></p>';
        }

        content.innerHTML =
            '<div class="match-result">' +
                '<div class="score strong" style="font-size:48px; color:var(--success);">&#10003;</div>' +
                '<div class="interpretation" style="color:var(--success);">Enrollment Successful</div>' +
                '<div class="details">' +
                    '<p><strong>Minutiae Detected:</strong> ' + (data.minutiae_count || 'N/A') + '</p>' +
                    '<p><strong>Finger Type:</strong> ' + (data.finger_type || 'N/A') + '</p>' +
                    qualityHtml +
                '</div>' +
            '</div>';
    } else {
        content.innerHTML =
            '<div class="match-result">' +
                '<div class="score none" style="font-size:48px; color:var(--danger);">&#10007;</div>' +
                '<div class="interpretation" style="color:var(--danger);">Enrollment Failed</div>' +
                '<div class="details">' +
                    '<p>' + (data.error || 'Unknown error') + '</p>' +
                    (data.minutiae_count !== undefined ? '<p><strong>Minutiae Detected:</strong> ' + data.minutiae_count + '</p>' : '') +
                '</div>' +
            '</div>';
    }

    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
