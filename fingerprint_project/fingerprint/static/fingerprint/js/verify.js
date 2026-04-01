/**
 * Verify — fingerprint matching
 */
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('fingerprint_image');
    const preview = document.getElementById('image-preview');
    const form = document.getElementById('verify-form');

    if (!fileInput || !preview) return;

    // Image preview
    fileInput.addEventListener('change', function() {
        const file = this.files[0];
        if (!file) {
            preview.innerHTML = '<div class="placeholder"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg><div>Select a fingerprint image to preview</div></div>';
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
        btnText.textContent = 'Matching...';
        spinner.style.display = 'inline-block';

        const formData = new FormData(form);

        // Remove empty student_id
        if (!formData.get('student_id')) {
            formData.delete('student_id');
        }

        fetch('/api/fingerprint/match/', {
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
            btnText.textContent = 'Match Fingerprint';
            spinner.style.display = 'none';

            showMatchResult(result.data, result.ok);
        })
        .catch(function(err) {
            btn.disabled = false;
            btnText.textContent = 'Match Fingerprint';
            spinner.style.display = 'none';
            showToast('Network error: ' + err.message, 'error');
        });
    });
});

function showMatchResult(data, success) {
    const card = document.getElementById('result-card');
    const content = document.getElementById('result-content');
    card.style.display = 'block';

    if (!success) {
        content.innerHTML =
            '<div class="match-result">' +
                '<div class="score none" style="font-size:48px; color:var(--danger);">&#10007;</div>' +
                '<div class="interpretation" style="color:var(--danger);">Error</div>' +
                '<div class="details"><p>' + (data.error || 'Match failed') + '</p></div>' +
            '</div>';
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
    }

    const score = data.score || 0;
    const interpretation = data.interpretation || 'NO_MATCH';
    const matchFound = data.match_found || false;

    let scoreClass = 'none';
    let scoreColor = 'var(--gray-400)';
    if (score >= 40) { scoreClass = 'strong'; scoreColor = 'var(--success)'; }
    else if (score >= 30) { scoreClass = 'possible'; scoreColor = 'var(--warning)'; }
    else if (score >= 20) { scoreClass = 'weak'; scoreColor = 'var(--danger)'; }

    let studentInfo = '';
    if (matchFound && data.full_name) {
        studentInfo =
            '<div style="margin-top:20px; padding:16px; background:var(--success-light); border-radius:var(--radius);">' +
                '<p style="font-size:16px; font-weight:600; color:var(--success); margin-bottom:8px;">&#10003; Match Found</p>' +
                '<p><strong>Name:</strong> ' + data.full_name + '</p>' +
                '<p><strong>Registration:</strong> ' + (data.registration_no || 'N/A') + '</p>' +
                '<p><strong>Student ID:</strong> ' + (data.student_id || 'N/A') + '</p>' +
                '<a href="/student/' + data.student_id + '/" class="btn btn-outline btn-sm" style="margin-top:8px;">View Student</a>' +
            '</div>';
    } else {
        studentInfo =
            '<div style="margin-top:20px; padding:16px; background:var(--danger-light); border-radius:var(--radius);">' +
                '<p style="font-size:16px; font-weight:600; color:var(--danger);">&#10007; No Matching Student Found</p>' +
                '<p style="color:var(--gray-600); font-size:14px;">The fingerprint did not match any enrolled student.</p>' +
            '</div>';
    }

    content.innerHTML =
        '<div class="match-result">' +
            '<div class="score ' + scoreClass + '">' + score.toFixed(1) + '</div>' +
            '<div class="interpretation" style="color:' + scoreColor + ';">' + interpretation.replace(/_/g, ' ') + '</div>' +
            '<div class="details">' +
                '<p><strong>Method:</strong> ' + (data.method || 'combined') + '</p>' +
                '<p><strong>Threshold:</strong> 30.0</p>' +
            '</div>' +
            studentInfo +
        '</div>';

    if (matchFound) {
        showToast('Fingerprint matched!', 'success');
    } else {
        showToast('No match found', 'warning');
    }

    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
