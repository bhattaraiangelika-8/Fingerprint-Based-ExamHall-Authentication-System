/**
 * Enroll — student registration form submission
 */
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('enroll-form');
    if (!form) return;

    form.addEventListener('submit', function(e) {
        e.preventDefault();

        const btn = document.getElementById('submit-btn');
        const btnText = btn.querySelector('.btn-text');
        const spinner = btn.querySelector('.spinner');
        btn.disabled = true;
        btnText.textContent = 'Registering...';
        spinner.style.display = 'inline-block';

        const formData = new FormData(form);

        // Handle consent checkbox
        const consent = document.getElementById('consent_signed');
        formData.set('consent_signed', consent.checked ? 'true' : 'false');

        fetch('/api/students/', {
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
            if (result.ok) {
                const studentId = result.data.student_id;
                showToast('Student registered successfully!', 'success');
                setTimeout(function() {
                    window.location.href = '/enroll/' + studentId + '/fingerprint/';
                }, 1000);
            } else {
                const data = result.data;
                let errorMsg = '';
                for (const key in data) {
                    if (Array.isArray(data[key])) {
                        errorMsg += key + ': ' + data[key].join(', ') + '. ';
                    } else {
                        errorMsg += key + ': ' + data[key] + '. ';
                    }
                }
                showToast('Error: ' + (errorMsg || 'Registration failed'), 'error');
                btn.disabled = false;
                btnText.textContent = 'Register & Continue to Fingerprint';
                spinner.style.display = 'none';
            }
        })
        .catch(function(err) {
            showToast('Network error: ' + err.message, 'error');
            btn.disabled = false;
            btnText.textContent = 'Register & Continue to Fingerprint';
            spinner.style.display = 'none';
        });
    });
});
