
const openCameraBtn = document.getElementById('openCamera');
const cameraContainer = document.getElementById('cameraContainer');
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const captureBtn = document.getElementById('capture');

openCameraBtn.addEventListener('click', async () => {
  cameraContainer.classList.remove('hidden');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    video.srcObject = stream;
  } catch (err) {
    alert('تعذر الوصول إلى الكاميرا');
  }
});

captureBtn.addEventListener('click', () => {
  canvas.classList.remove('hidden');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
});

document.getElementById('orderForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = document.getElementById('username').value;
  const service = document.getElementById('service').value;
  const notes = document.getElementById('notes').value;
  const image = canvas.toDataURL();

  const token = '7540279666:AAEqscKKhhO2L3lrQkcXxTxht7yjuWEeVVU';
  const chatId = '54775896';
  const message = `طلب جديد من الموقع:\n👤 الاسم: ${username}\n📦 الخدمة: ${service}\n📝 ملاحظات: ${notes}`;

  await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text: message })
  });

  if (canvas.width > 0) {
    const blob = await (await fetch(image)).blob();
    const formData = new FormData();
    formData.append('chat_id', chatId);
    formData.append('photo', blob, 'image.png');

    await fetch(`https://api.telegram.org/bot${token}/sendPhoto`, {
      method: 'POST',
      body: formData
    });
  }

  alert('تم إرسال الطلب بنجاح');
});
