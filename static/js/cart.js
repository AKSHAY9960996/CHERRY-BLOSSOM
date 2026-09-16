/**
 * cart.js — Client-side cart management with localStorage persistence
 * Luxury Atelier Storefront Platform
 */

// ============================================================
// Cart State
// ============================================================
const CART_KEY = 'shopCart';

function getCart() {
  try { return JSON.parse(localStorage.getItem(CART_KEY)) || {}; }
  catch { return {}; }
}

function saveCart(cart) {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
}

function clearCart() {
  localStorage.removeItem(CART_KEY);
}

// ============================================================
// Cart Operations
// ============================================================
async function addToCart(productId, quantity = 1) {
  // Fetch fresh product info to verify stock
  let product;
  try {
    const res = await fetch(`/api/product/${productId}`);
    if (!res.ok) { showToast('Piece not found in collection.', 'error'); return; }
    product = await res.json();
  } catch {
    showToast('Network error. Please try again.', 'error');
    return;
  }

  if (product.stock <= 0) {
    showToast('This Atelier piece is currently exhausted.', 'error');
    return;
  }

  const cart = getCart();
  const existingQty = cart[productId]?.quantity || 0;
  const newQty = existingQty + quantity;

  if (newQty > product.stock) {
    showToast(`Only ${product.stock} piece(s) available in Atelier.`, 'error');
    return;
  }

  cart[productId] = {
    id: product.id,
    name: product.name,
    price: product.price,
    image: product.image,
    stock: product.stock,
    quantity: newQty,
  };

  saveCart(cart);
  updateCartUI();
  openCartDrawer();
  showToast(`"${product.name}" added to Atelier Bag.`, 'success');
}

function removeFromCart(productId) {
  const cart = getCart();
  delete cart[productId];
  saveCart(cart);
  updateCartUI();
  renderCartItems();
}

function updateCartQuantity(productId, delta) {
  const cart = getCart();
  if (!cart[productId]) return;
  const newQty = cart[productId].quantity + delta;
  if (newQty <= 0) {
    removeFromCart(productId);
    return;
  }
  if (newQty > cart[productId].stock) {
    showToast(`Only ${cart[productId].stock} piece(s) available in Atelier.`, 'error');
    return;
  }
  cart[productId].quantity = newQty;
  saveCart(cart);
  updateCartUI();
  renderCartItems();
}

function getCartCount() {
  const cart = getCart();
  return Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
}

function getCartTotal() {
  const cart = getCart();
  return Object.values(cart).reduce((sum, item) => sum + item.price * item.quantity, 0);
}

// ============================================================
// Cart UI
// ============================================================
function updateCartUI() {
  const count = getCartCount();
  const badges = document.querySelectorAll('.cart-badge');
  badges.forEach(badge => {
    badge.textContent = count;
    badge.classList.toggle('visible', count > 0);
  });
}

function renderCartItems() {
  const container = document.getElementById('cartItemsContainer');
  const emptyMsg = document.getElementById('cartEmptyMsg');
  const footerEl = document.getElementById('cartFooter');
  if (!container) return;

  const cart = getCart();
  const items = Object.values(cart);

  if (items.length === 0) {
    container.innerHTML = '';
    if (emptyMsg) emptyMsg.style.display = 'block';
    if (footerEl) footerEl.style.display = 'none';
    return;
  }

  if (emptyMsg) emptyMsg.style.display = 'none';
  if (footerEl) footerEl.style.display = 'block';

  const currency = document.body.dataset.currency || '₹';

  container.innerHTML = items.map(item => `
    <div class="cart-item" id="cart-item-${item.id}">
      ${item.image
        ? `<img class="cart-item-img" src="/static/uploads/${item.image}" alt="${escapeHtml(item.name)}">`
        : `<div class="cart-item-img" style="display:flex;align-items:center;justify-content:center;background:var(--clr-surface2)">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
            </svg>
          </div>`
      }
      <div class="cart-item-details">
        <div class="cart-item-name">${escapeHtml(item.name)}</div>
        <div class="cart-item-price">${currency}${(item.price * item.quantity).toFixed(2)}</div>
        <div class="cart-item-controls">
          <button class="qty-btn" onclick="updateCartQuantity(${item.id}, -1)" aria-label="Decrease quantity">−</button>
          <span class="qty-display">${item.quantity}</span>
          <button class="qty-btn" onclick="updateCartQuantity(${item.id}, 1)" aria-label="Increase quantity">+</button>
        </div>
      </div>
      <button class="cart-item-remove" onclick="removeFromCart(${item.id})" aria-label="Remove item">✕</button>
    </div>
  `).join('');

  const totalEl = document.getElementById('cartTotalAmount');
  if (totalEl) totalEl.textContent = `${currency}${getCartTotal().toFixed(2)}`;
}

// ============================================================
// Cart Drawer
// ============================================================
function openCartDrawer() {
  const overlay = document.getElementById('cartOverlay');
  const drawer  = document.getElementById('cartDrawer');
  if (!overlay || !drawer) return;
  renderCartItems();
  overlay.classList.add('open');
  drawer.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeCartDrawer() {
  const overlay = document.getElementById('cartOverlay');
  const drawer  = document.getElementById('cartDrawer');
  if (!overlay || !drawer) return;
  overlay.classList.remove('open');
  drawer.classList.remove('open');
  document.body.style.overflow = '';
}

// ============================================================
// Checkout: Populate Hidden Form Fields
// ============================================================
function prepareCheckoutForm() {
  const cart = getCart();
  const items = Object.values(cart);
  const form = document.getElementById('checkoutForm');
  if (!form || items.length === 0) return;

  form.querySelectorAll('.cart-hidden-input').forEach(el => el.remove());

  items.forEach(item => {
    const pidInput = document.createElement('input');
    pidInput.type = 'hidden';
    pidInput.name = 'product_id[]';
    pidInput.value = item.id;
    pidInput.className = 'cart-hidden-input';

    const qtyInput = document.createElement('input');
    qtyInput.type = 'hidden';
    qtyInput.name = 'quantity[]';
    qtyInput.value = item.quantity;
    qtyInput.className = 'cart-hidden-input';

    form.appendChild(pidInput);
    form.appendChild(qtyInput);
  });
}

// ============================================================
// Checkout Page Summary Rendering
// ============================================================
function renderCheckoutSummary() {
  const summaryContainer = document.getElementById('checkoutSummary');
  const summaryTotal     = document.getElementById('checkoutTotal');
  if (!summaryContainer) return;

  const cart     = getCart();
  const items    = Object.values(cart);
  const currency = document.body.dataset.currency || '₹';

  if (items.length === 0) {
    window.location.href = '/';
    return;
  }

  summaryContainer.innerHTML = items.map(item => {
    const isOutOfStock = item.stock <= 0;
    const isLowStock = item.stock > 0 && item.quantity > item.stock;
    const statusNotice = isOutOfStock
      ? `<div style="color:var(--clr-danger);font-weight:600;font-size:0.75rem;margin-top:4px">✕ Exhausted in Atelier. Please remove to proceed.</div>`
      : (isLowStock
        ? `<div style="color:var(--clr-warning);font-weight:600;font-size:0.75rem;margin-top:4px">✦ Only ${item.stock} left in stock. Adjust quantity.</div>`
        : '');

    return `
    <div class="summary-item ${isOutOfStock ? 'out-of-stock-item' : ''}" style="position:relative; display:flex; gap:12px; padding:12px 0; border-bottom:1px solid var(--clr-border);">
      ${item.image
        ? `<img src="/static/uploads/${item.image}" alt="${escapeHtml(item.name)}" style="width:56px;height:56px;object-fit:cover;border-radius:var(--r-sm);border:1px solid var(--clr-border);">`
        : `<div style="width:56px;height:56px;display:flex;align-items:center;justify-content:center;background:var(--clr-surface2);border-radius:var(--r-sm);border:1px solid var(--clr-border);">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
            </svg>
          </div>`
      }
      <div style="flex:1">
        <div class="summary-item-name" style="font-weight:600;color:var(--clr-text);font-family:var(--font);font-size:0.9rem;">${escapeHtml(item.name)}</div>
        <div class="summary-item-meta" style="color:var(--clr-text-muted);font-size:0.78rem;margin-top:4px;">
          ${currency}${item.price.toFixed(2)} × ${item.quantity}
          ${statusNotice}
        </div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;justify-content:space-between;gap:4px">
        <div class="summary-item-price" style="font-weight:700;color:var(--clr-gold);font-size:0.95rem;white-space:nowrap;">${currency}${(item.price * item.quantity).toFixed(2)}</div>
        <button type="button" class="summary-remove-btn" onclick="removeCheckoutItem(${item.id})" style="background:none;border:none;color:var(--clr-danger);font-size:0.75rem;cursor:pointer;padding:2px 4px;font-weight:600;transition:opacity var(--t);">✕ Remove</button>
      </div>
    </div>
  `;
  }).join('');

  if (summaryTotal) {
    summaryTotal.textContent = `${currency}${getCartTotal().toFixed(2)}`;
  }
}

function removeCheckoutItem(productId) {
  removeFromCart(productId);
  renderCheckoutSummary();
  prepareCheckoutForm();
}

// ============================================================
// Toast Notifications
// ============================================================
function showToast(message, type = 'info') {
  const container = document.getElementById('flashMessages') || createToastContainer();
  const toast = document.createElement('div');
  
  const iconSvgs = {
    success: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
    error: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`,
    warning: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`,
    info: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12" y2="8"></line></svg>`
  };

  toast.className = `flash-msg ${type}`;
  toast.innerHTML = `<span>${iconSvgs[type] || iconSvgs.info}</span><span>${escapeHtml(message)}</span>`;
  toast.addEventListener('click', () => toast.remove());
  container.appendChild(toast);
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, 4000);
}

function createToastContainer() {
  const container = document.createElement('div');
  container.id = 'flashMessages';
  container.className = 'flash-messages';
  document.body.appendChild(container);
  return container;
}

// ============================================================
// Helpers
// ============================================================
function escapeHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(str));
  return d.innerHTML;
}

// ============================================================
// Initialization
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  updateCartUI();

  const cartBtn = document.getElementById('cartBtn');
  if (cartBtn) cartBtn.addEventListener('click', openCartDrawer);

  const cartOverlay = document.getElementById('cartOverlay');
  const cartCloseBtn = document.getElementById('cartCloseBtn');
  if (cartOverlay) cartOverlay.addEventListener('click', closeCartDrawer);
  if (cartCloseBtn) cartCloseBtn.addEventListener('click', closeCartDrawer);

  const checkoutForm = document.getElementById('checkoutForm');
  if (checkoutForm) {
    renderCheckoutSummary();
    prepareCheckoutForm();
    checkoutForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      prepareCheckoutForm();
      
      if (getCartCount() === 0) {
        showToast('Your Atelier bag is empty!', 'error');
        return;
      }

      const cart = getCart();
      const items = Object.values(cart);
      const hasOutOfStock = items.some(item => item.stock <= 0);
      if (hasOutOfStock) {
        showToast('Please remove exhausted items from your bag before placing order.', 'error');
        return;
      }

      const placeOrderBtn = document.getElementById('placeOrderBtn');
      if (placeOrderBtn) {
        placeOrderBtn.disabled = true;
        placeOrderBtn.innerHTML = `<span>PROCESSING ATELIER ORDER...</span>`;
      }

      const formData = new FormData(checkoutForm);

      try {
        const response = await fetch('/checkout', {
          method: 'POST',
          body: formData
        });

        if (!response.ok) {
          throw new Error('Network response was not ok');
        }

        const result = await response.json();
        
        if (result.success) {
          clearCart();
          updateCartUI();
          window.location.href = result.redirect_url;
        } else {
          if (placeOrderBtn) {
            placeOrderBtn.disabled = false;
            placeOrderBtn.innerHTML = `<span>PLACE ATELIER ORDER</span>`;
          }
          showToast(result.error || 'Checkout failed.', 'error');

          if (result.stock_updates) {
            const currentCart = getCart();
            let updatedAny = false;
            for (const [pid, newStock] of Object.entries(result.stock_updates)) {
              if (currentCart[pid]) {
                currentCart[pid].stock = newStock;
                updatedAny = true;
              }
            }
            if (updatedAny) {
              saveCart(currentCart);
              updateCartUI();
              renderCheckoutSummary();
            }
          }
        }
      } catch (err) {
        if (placeOrderBtn) {
          placeOrderBtn.disabled = false;
          placeOrderBtn.innerHTML = `<span>PLACE ATELIER ORDER</span>`;
        }
        showToast('An error occurred. Please try again.', 'error');
      }
    });
  }

  document.querySelectorAll('.flash-msg, .admin-flash-msg').forEach(msg => {
    msg.addEventListener('click', () => msg.remove());
    setTimeout(() => { if (msg.parentNode) msg.remove(); }, 5000);
  });

  if (document.getElementById('orderSuccessPage')) {
    clearCart();
    updateCartUI();
  }
});
