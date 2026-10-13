/**
 * NutriAI - Client Application Logic
 * Clean, secure, accessible state management and API communication.
 */

const API_BASE = window.location.origin;

// State
let authToken = localStorage.getItem("nutri_token") || null;
let currentUser = JSON.parse(localStorage.getItem("nutri_user") || "null");
let currentConversationId = null;
let currentTrackingDate = new Date().toISOString().split("T")[0];
let verifiedFoodsList = [];

// Helper: Escape HTML to prevent XSS
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Helper: Authenticated API Fetch
async function apiRequest(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {})
  };

  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const res = await fetch(url, { ...options, headers });
  
  if (res.status === 401 && !endpoint.includes("/auth/login") && !endpoint.includes("/auth/signup")) {
    handleLogout();
    throw new Error("Session expired. Please log in again.");
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Server error (${res.status})`);
  }
  return data;
}

// ==========================================================================
// Authentication & Session
// ==========================================================================

async function initAuth() {
  if (authToken) {
    try {
      const data = await apiRequest("/api/auth/me");
      currentUser = data.user;
      localStorage.setItem("nutri_user", JSON.stringify(currentUser));
      renderAuthState(true);
      loadWorkspace();
      return;
    } catch (e) {
      console.warn("Session check failed:", e.message);
      handleLogout();
    }
  }
  renderAuthState(false);
}

function renderAuthState(isLoggedIn) {
  const heroSection = document.getElementById("heroLanding");
  const appWorkspace = document.getElementById("appWorkspace");
  const guestNav = document.getElementById("guestNavActions");
  const authNav = document.getElementById("authNavActions");
  const userNameSpan = document.getElementById("navUserName");

  if (isLoggedIn && currentUser) {
    if (heroSection) heroSection.style.display = "none";
    if (appWorkspace) appWorkspace.style.display = "flex";
    if (guestNav) guestNav.style.display = "none";
    if (authNav) authNav.style.display = "flex";
    if (userNameSpan) userNameSpan.textContent = currentUser.name.split(" ")[0];
  } else {
    if (heroSection) heroSection.style.display = "grid";
    if (appWorkspace) appWorkspace.style.display = "none";
    if (guestNav) guestNav.style.display = "flex";
    if (authNav) authNav.style.display = "none";
  }
}

function openAuth(tab = "login") {
  const overlay = document.getElementById("authOverlay");
  const errorBanner = document.getElementById("authErrorBanner");
  if (errorBanner) errorBanner.style.display = "none";
  if (overlay) overlay.classList.add("active");
  if (tab === "signup") showSignup();
  else showLogin();
}

function closeAuth() {
  const overlay = document.getElementById("authOverlay");
  if (overlay) overlay.classList.remove("active");
}

function showLogin() {
  document.getElementById("loginForm").classList.remove("hidden");
  document.getElementById("signupForm").classList.add("hidden");
  document.getElementById("loginTabBtn").classList.add("active");
  document.getElementById("signupTabBtn").classList.remove("active");
}

function showSignup() {
  document.getElementById("signupForm").classList.remove("hidden");
  document.getElementById("loginForm").classList.add("hidden");
  document.getElementById("signupTabBtn").classList.add("active");
  document.getElementById("loginTabBtn").classList.remove("active");
}

function showAuthError(msg) {
  const banner = document.getElementById("authErrorBanner");
  if (banner) {
    banner.textContent = msg;
    banner.style.display = "block";
  }
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const email = document.getElementById("loginEmail").value.trim();
  const password = document.getElementById("loginPassword").value;
  const submitBtn = e.target.querySelector("button[type='submit']");

  try {
    submitBtn.disabled = true;
    submitBtn.textContent = "Logging in...";
    const data = await apiRequest("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password })
    });

    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem("nutri_token", authToken);
    localStorage.setItem("nutri_user", JSON.stringify(currentUser));

    closeAuth();
    renderAuthState(true);
    loadWorkspace();
  } catch (err) {
    showAuthError(err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Login";
  }
}

async function handleSignupSubmit(e) {
  e.preventDefault();
  const name = document.getElementById("signupName").value.trim();
  const email = document.getElementById("signupEmail").value.trim();
  const password = document.getElementById("signupPassword").value;
  const submitBtn = e.target.querySelector("button[type='submit']");

  if (password.length < 8) {
    showAuthError("Password must be at least 8 characters long.");
    return;
  }

  try {
    submitBtn.disabled = true;
    submitBtn.textContent = "Creating Account...";
    const data = await apiRequest("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ name, email, password })
    });

    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem("nutri_token", authToken);
    localStorage.setItem("nutri_user", JSON.stringify(currentUser));

    closeAuth();
    renderAuthState(true);
    loadWorkspace();
  } catch (err) {
    showAuthError(err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Create Account";
  }
}

async function handleLogout() {
  try {
    if (authToken) {
      await apiRequest("/api/auth/logout", { method: "POST" });
    }
  } catch (_) {}
  authToken = null;
  currentUser = null;
  localStorage.removeItem("nutri_token");
  localStorage.removeItem("nutri_user");
  renderAuthState(false);
}

// ==========================================================================
// Workspace Navigation & Tabs
// ==========================================================================

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-content").forEach(content => {
    content.classList.toggle("active", content.id === `tab-${tabName}`);
  });

  if (tabName === "dashboard") loadDashboard();
  if (tabName === "chat") loadChatWorkspace();
  if (tabName === "meals") loadMealsTracker();
  if (tabName === "progress") loadProgressTracker();
  if (tabName === "profile") loadProfileTab();
}

function loadWorkspace() {
  switchTab("dashboard");
  loadVerifiedFoods();
}

// ==========================================================================
// Tab 1: Dashboard
// ==========================================================================

async function loadDashboard() {
  try {
    const today = new Date().toISOString().split("T")[0];
    const [mealsData, waterData, profileData, plansData] = await Promise.all([
      apiRequest(`/api/meals?date=${today}`),
      apiRequest(`/api/water?date=${today}`),
      apiRequest("/api/profile"),
      apiRequest("/api/plans")
    ]);

    // Update calories
    const totals = mealsData.totals;
    document.getElementById("dashCalories").textContent = Math.round(totals.calories).toLocaleString();
    document.getElementById("dashCalorieTarget").textContent = `Target: ${totals.calorie_target} kcal`;
    document.getElementById("dashCalorieBar").style.width = `${Math.min(totals.progress_percent, 100)}%`;

    // Macros
    document.getElementById("macroProtein").textContent = `${Math.round(totals.protein_g)}g`;
    document.getElementById("macroCarbs").textContent = `${Math.round(totals.carbs_g)}g`;
    document.getElementById("macroFat").textContent = `${Math.round(totals.fat_g)}g`;

    // Water
    document.getElementById("dashWater").textContent = `${waterData.glasses} / ${waterData.target_glasses}`;
    document.getElementById("dashWaterSub").textContent = `${waterData.total_ml} ml of ${waterData.target_ml} ml target`;
    document.getElementById("dashWaterBar").style.width = `${Math.min(waterData.progress_percent, 100)}%`;

    // Goal
    const goalName = (profileData.profile && profileData.profile.goal) ? profileData.profile.goal.replace(/_/g, " ") : "Healthy Lifestyle";
    document.getElementById("dashGoal").textContent = goalName.charAt(0).toUpperCase() + goalName.slice(1);

    // Latest Saved Plan
    const planCard = document.getElementById("dashPlanCard");
    if (plansData.plans && plansData.plans.length > 0) {
      const latestPlan = plansData.plans[0];
      planCard.innerHTML = `
        <div class="dash-card-header">
          <span class="dash-card-title">🥗 Saved Diet Plan</span>
          <button class="btn-secondary" style="padding: 0.3rem 0.8rem; font-size: 0.8rem;" onclick="switchTab('chat')">Open AI Chat</button>
        </div>
        <h4 style="margin-bottom: 0.5rem; color: var(--color-primary);">${escapeHtml(latestPlan.title)}</h4>
        <div style="font-size: 0.9rem; line-height: 1.6; max-height: 150px; overflow-y: auto;">
          ${formatDietPlan(latestPlan.plan_content)}
        </div>
      `;
    } else {
      planCard.innerHTML = `
        <div class="dash-card-header">
          <span class="dash-card-title">🥗 Today’s Diet Plan</span>
        </div>
        <div class="empty-state" style="padding: 1.5rem 0;">
          <p>No diet plan saved yet.</p>
          <button class="btn-primary" style="margin-top: 0.75rem;" onclick="switchTab('chat')">Generate with AI ✨</button>
        </div>
      `;
    }
  } catch (err) {
    console.error("Dashboard load error:", err);
  }
}

// ==========================================================================
// Tab 2: AI Nutritionist Chat Workspace
// ==========================================================================

async function loadChatWorkspace() {
  await loadConversationsList();
  if (!currentConversationId) {
    await handleNewConversation();
  }
  const chatInput = document.getElementById("chatInput");
  if (chatInput) {
    chatInput.focus();
  }
  scrollChatToBottom(false);
}

async function loadConversationsList() {
  try {
    const data = await apiRequest("/api/conversations");
    const listEl = document.getElementById("conversationsList");
    listEl.innerHTML = "";

    if (!data.conversations || data.conversations.length === 0) {
      listEl.innerHTML = '<div style="color: var(--text-dim); font-size: 0.85rem; padding: 0.5rem;">No previous chats</div>';
      return;
    }

    data.conversations.forEach(conv => {
      const item = document.createElement("div");
      item.className = `conv-item ${conv.id === currentConversationId ? "active" : ""}`;
      item.onclick = () => selectConversation(conv.id);

      item.innerHTML = `
        <span class="conv-title">💬 ${escapeHtml(conv.title)}</span>
        <button class="conv-delete-btn" onclick="handleDeleteConv('${conv.id}', event)" title="Delete Chat">×</button>
      `;
      listEl.appendChild(item);
    });
  } catch (err) {
    console.error("Error loading conversations:", err);
  }
}

async function handleNewConversation() {
  try {
    const res = await apiRequest("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: "New Nutrition Consultation" })
    });
    currentConversationId = res.conversation_id;
    await loadConversationsList();
    selectConversation(currentConversationId);
  } catch (err) {
    alert("Could not start a new chat: " + err.message);
  }
}

async function selectConversation(convId) {
  currentConversationId = convId;
  document.querySelectorAll(".conv-item").forEach(el => el.classList.remove("active"));
  await loadConversationsList();

  const messagesContainer = document.getElementById("chatMessages");
  messagesContainer.innerHTML = '<div class="empty-state"><p>Loading messages...</p></div>';

  try {
    const data = await apiRequest(`/api/conversations/${convId}`);
    messagesContainer.innerHTML = "";

    if (!data.messages || data.messages.length === 0) {
      messagesContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🤖</div>
          <h3>Your AI Nutritionist is Ready</h3>
          <p>Tell me your health goal, food preferences, weight, or ask for a personalized meal plan.</p>
        </div>
      `;
      return;
    }

    data.messages.forEach(msg => {
      appendChatMessage(msg.role, msg.content, false);
    });
    scrollChatToBottom(false);
  } catch (err) {
    messagesContainer.innerHTML = `<div class="empty-state"><p>Error loading messages: ${escapeHtml(err.message)}</p></div>`;
  }
}

async function handleDeleteConv(convId, e) {
  e.stopPropagation();
  if (!confirm("Are you sure you want to delete this consultation?")) return;
  try {
    await apiRequest(`/api/conversations/${convId}`, { method: "DELETE" });
    if (currentConversationId === convId) {
      currentConversationId = null;
    }
    await loadConversationsList();
    if (!currentConversationId) {
      await handleNewConversation();
    }
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

function scrollChatToBottom(smooth = true) {
  const container = document.getElementById("chatMessages");
  if (!container) return;

  // Immediate scroll
  container.scrollTop = container.scrollHeight;

  // Delayed reflow scroll to account for dynamic HTML card expansion
  setTimeout(() => {
    container.scrollTo({
      top: container.scrollHeight,
      behavior: smooth ? "smooth" : "auto"
    });
    const lastRow = container.querySelector(".chat-message-row:last-child");
    if (lastRow) {
      lastRow.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "end" });
    }
  }, 60);
}

function appendChatMessage(role, content, scrollToBottom = true) {
  const container = document.getElementById("chatMessages");
  const row = document.createElement("div");
  row.className = `chat-message-row ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "chat-avatar";
  avatar.textContent = role === "user" ? "👤" : "🤖";

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble-content";

  if (role === "assistant") {
    bubble.innerHTML = formatDietPlan(content);
  } else {
    bubble.textContent = content;
  }

  row.appendChild(avatar);
  row.appendChild(bubble);
  container.appendChild(row);

  if (scrollToBottom) {
    scrollChatToBottom(true);
  }
}

let lastFailedChatMessage = "";

function formatDietPlan(text) {
  if (!text) return "";
  const escaped = escapeHtml(text);

  // Check if response contains structured diet plan sections
  const hasPlan = escaped.includes("Goal:") || escaped.includes("Breakfast:") || escaped.includes("Lunch:");

  let formatted = escaped
    .replace(/(🎯?\s*Goal:)/gi, '<div class="diet-plan-section-title">🎯 Goal:</div>')
    .replace(/(🥣?\s*Breakfast:)/gi, '<div class="diet-plan-section-title">🥣 Breakfast:</div>')
    .replace(/(🍛?\s*Lunch:)/gi, '<div class="diet-plan-section-title">🍛 Lunch:</div>')
    .replace(/(☕?\s*Evening Snack:)/gi, '<div class="diet-plan-section-title">☕ Evening Snack:</div>')
    .replace(/(🌙?\s*Dinner:)/gi, '<div class="diet-plan-section-title">🌙 Dinner:</div>')
    .replace(/(💧?\s*Water Intake:)/gi, '<div class="diet-plan-section-title">💧 Water Intake:</div>')
    .replace(/(🏃?\s*Exercise Tip:)/gi, '<div class="diet-plan-section-title">🏃 Exercise Tip:</div>')
    .replace(/(⚠️?\s*Important Note:)/gi, '<div class="diet-plan-section-title">⚠️ Important Note:</div>')
    .replace(/\[Verified Database Record\]/gi, '<span class="badge-verified">✓ Verified Database Record</span>')
    .replace(/\[Verified Dataset\]/gi, '<span class="badge-verified">✓ Verified Dataset</span>')
    .replace(/\[Verified Composition Record\]/gi, '<span class="badge-verified">✓ Verified Composition</span>')
    .replace(/\[Verified Database\]/gi, '<span class="badge-verified">✓ Verified Database</span>')
    .replace(/\[Verified Records\]/gi, '<span class="badge-verified">✓ Verified Records</span>')
    .replace(/\[Verified Tracking Record\]/gi, '<span class="badge-verified">✓ Verified Tracking</span>')
    .replace(/\[Approximate AI Estimates?\]/gi, '<span class="badge-estimate">~ Approximate AI Estimate</span>')
    .replace(/\[Approximate\]/gi, '<span class="badge-estimate">~ Estimate</span>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>');

  if (hasPlan) {
    const rawAttr = encodeURIComponent(text);
    return `
      <div class="diet-plan-card">
        <div class="diet-plan-header">
          <strong>🥗 AI Nutrition Plan</strong>
          <button class="save-plan-btn" onclick="savePlanFromChat('${rawAttr}')">📌 Save Plan to Dashboard</button>
        </div>
        ${formatted}
      </div>
    `;
  }

  return formatted;
}

async function savePlanFromChat(encodedPlan) {
  const planText = decodeURIComponent(encodedPlan);
  const title = prompt("Enter a title for this diet plan:", "Daily Nutrition Plan");
  if (!title) return;

  try {
    await apiRequest("/api/plans", {
      method: "POST",
      body: JSON.stringify({ title, plan_content: planText })
    });
    alert("Plan saved successfully to your dashboard!");
  } catch (err) {
    alert("Could not save plan: " + err.message);
  }
}

async function handleSendMessage() {
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text) return;

  lastFailedChatMessage = text;

  if (!currentConversationId) {
    await handleNewConversation();
  }

  appendChatMessage("user", text);
  input.value = "";

  // Dynamic loading bubble with pulse animation
  const container = document.getElementById("chatMessages");
  const loadingRow = document.createElement("div");
  loadingRow.className = "chat-message-row assistant";
  loadingRow.id = "chatLoadingIndicator";
  loadingRow.innerHTML = `
    <div class="chat-avatar">🤖</div>
    <div class="chat-bubble-content" style="color: var(--text-muted);">
      <span class="chat-loading-pulse">
        <span>NutriAI is analyzing</span>
        <span class="chat-loading-dot"></span>
        <span class="chat-loading-dot"></span>
        <span class="chat-loading-dot"></span>
      </span>
    </div>
  `;
  container.appendChild(loadingRow);
  scrollChatToBottom(true);

  try {
    const res = await apiRequest(`/api/conversations/${currentConversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message: text })
    });
    loadingRow.remove();
    appendChatMessage("assistant", res.reply);
    loadConversationsList();
    lastFailedChatMessage = "";
  } catch (err) {
    loadingRow.remove();
    const errorBubble = `⚠️ ${escapeHtml(err.message)} <br><button class="btn-secondary" style="padding: 0.25rem 0.65rem; font-size: 0.8rem; margin-top: 0.5rem;" onclick="retryLastMessage()">🔄 Retry</button>`;
    const errRow = document.createElement("div");
    errRow.className = "chat-message-row assistant";
    errRow.innerHTML = `
      <div class="chat-avatar">🤖</div>
      <div class="chat-bubble-content" style="border-color: rgba(239, 68, 68, 0.4);">${errorBubble}</div>
    `;
    container.appendChild(errRow);
    container.scrollTop = container.scrollHeight;
  }
}

function retryLastMessage() {
  if (lastFailedChatMessage) {
    const input = document.getElementById("chatInput");
    if (input) {
      input.value = lastFailedChatMessage;
      handleSendMessage();
    }
  }
}

// Quick reply helper from hero or chat
function quickPrompt(promptText) {
  const input = document.getElementById("chatInput");
  if (input) {
    input.value = promptText;
    handleSendMessage();
  }
}

// ==========================================================================
// Tab 3: Meals & Food Tracker
// ==========================================================================

async function loadVerifiedFoods() {
  try {
    const data = await apiRequest("/api/foods");
    verifiedFoodsList = data.foods || [];
    const selectEl = document.getElementById("foodSelect");
    if (selectEl) {
      selectEl.innerHTML = '<option value="">-- Choose from Verified Food List (Optional) --</option>';
      verifiedFoodsList.forEach(food => {
        const opt = document.createElement("option");
        opt.value = food.name;
        opt.textContent = `${food.name} (${food.calories} kcal / ${food.serving_unit})`;
        selectEl.appendChild(opt);
      });
    }
  } catch (err) {
    console.warn("Could not load verified foods list:", err);
  }
}

function handleFoodSelectionChange() {
  const select = document.getElementById("foodSelect");
  const selectedName = select.value;
  const food = verifiedFoodsList.find(f => f.name === selectedName);
  if (food) {
    document.getElementById("mealFoodName").value = food.name;
    document.getElementById("mealCalories").value = food.calories;
    document.getElementById("mealProtein").value = food.protein;
    document.getElementById("mealCarbs").value = food.carbs;
    document.getElementById("mealFat").value = food.fat;
    document.getElementById("mealServing").value = food.default_serving;
  }
}

async function loadMealsTracker() {
  const dateInput = document.getElementById("trackerDateInput");
  if (dateInput) {
    dateInput.value = currentTrackingDate;
  }

  try {
    const data = await apiRequest(`/api/meals?date=${currentTrackingDate}`);
    renderMealsSummary(data.totals);
    renderCategoryMeals("breakfast", data.meals_by_category.breakfast || []);
    renderCategoryMeals("lunch", data.meals_by_category.lunch || []);
    renderCategoryMeals("snack", data.meals_by_category.snack || []);
    renderCategoryMeals("dinner", data.meals_by_category.dinner || []);
  } catch (err) {
    console.error("Meals loading error:", err);
  }
}

function renderMealsSummary(totals) {
  document.getElementById("trackerTotalCalories").textContent = Math.round(totals.calories);
  document.getElementById("trackerCalorieTarget").textContent = totals.calorie_target;
  document.getElementById("trackerProtein").textContent = `${Math.round(totals.protein_g)}g`;
  document.getElementById("trackerCarbs").textContent = `${Math.round(totals.carbs_g)}g`;
  document.getElementById("trackerFat").textContent = `${Math.round(totals.fat_g)}g`;
}

function renderCategoryMeals(category, meals) {
  const container = document.getElementById(`${category}MealsList`);
  container.innerHTML = "";

  if (meals.length === 0) {
    container.innerHTML = '<div style="color: var(--text-dim); font-size: 0.85rem; padding: 0.5rem 0;">No food logged yet.</div>';
    return;
  }

  meals.forEach(m => {
    const row = document.createElement("div");
    row.className = "meal-item-row";
    row.innerHTML = `
      <div class="meal-item-info">
        <strong>${escapeHtml(m.food_name)}</strong>
        <small>${m.calories} kcal • P: ${m.protein}g | C: ${m.carbs}g | F: ${m.fat}g</small>
      </div>
      <button class="delete-icon-btn" onclick="handleDeleteMeal(${m.id})" title="Delete entry">🗑️</button>
    `;
    container.appendChild(row);
  });
}

async function handleAddMealSubmit(e) {
  e.preventDefault();
  const mealCategory = document.getElementById("mealCategory").value;
  const foodName = document.getElementById("mealFoodName").value.trim();
  const servingSize = parseFloat(document.getElementById("mealServing").value) || 1.0;
  const calories = parseFloat(document.getElementById("mealCalories").value) || 0.0;
  const protein = parseFloat(document.getElementById("mealProtein").value) || 0.0;
  const carbs = parseFloat(document.getElementById("mealCarbs").value) || 0.0;
  const fat = parseFloat(document.getElementById("mealFat").value) || 0.0;

  if (!foodName || calories < 0) {
    alert("Please enter a valid food name and calories.");
    return;
  }

  try {
    await apiRequest("/api/meals", {
      method: "POST",
      body: JSON.stringify({
        log_date: currentTrackingDate,
        meal_category: mealCategory,
        food_name: foodName,
        serving_size: servingSize,
        calories: calories,
        protein: protein,
        carbs: carbs,
        fat: fat
      })
    });
    // Reset form
    document.getElementById("addMealForm").reset();
    document.getElementById("foodSelect").value = "";
    loadMealsTracker();
  } catch (err) {
    alert("Could not log meal: " + err.message);
  }
}

async function handleDeleteMeal(mealId) {
  try {
    await apiRequest(`/api/meals/${mealId}`, { method: "DELETE" });
    loadMealsTracker();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

function handleTrackerDateChange(e) {
  currentTrackingDate = e.target.value;
  loadMealsTracker();
}

// ==========================================================================
// Tab 4: Water & Weight Tracker
// ==========================================================================

async function loadProgressTracker() {
  await Promise.all([loadWaterTracker(), loadWeightTracker()]);
}

async function loadWaterTracker() {
  try {
    const data = await apiRequest(`/api/water?date=${currentTrackingDate}`);
    document.getElementById("waterProgressDisplay").textContent = `${data.total_ml} ml`;
    document.getElementById("waterGlassesDisplay").textContent = `${data.glasses} of ${data.target_glasses} glasses`;
    document.getElementById("waterProgressBar").style.width = `${data.progress_percent}%`;
  } catch (err) {
    console.error("Water loading error:", err);
  }
}

async function handleAddWater(amount) {
  try {
    await apiRequest("/api/water", {
      method: "POST",
      body: JSON.stringify({ log_date: currentTrackingDate, amount_ml: amount })
    });
    loadWaterTracker();
  } catch (err) {
    alert("Could not log water: " + err.message);
  }
}

async function handleResetWater() {
  if (!confirm("Reset water for today?")) return;
  try {
    await apiRequest(`/api/water/reset?date=${currentTrackingDate}`, { method: "DELETE" });
    loadWaterTracker();
  } catch (err) {
    alert("Water reset failed: " + err.message);
  }
}

async function loadWeightTracker() {
  try {
    const data = await apiRequest("/api/weight");
    const history = data.history || [];
    renderWeightChart(history);
    renderWeightHistoryTable(history);
  } catch (err) {
    console.error("Weight loading error:", err);
  }
}

async function handleAddWeightSubmit(e) {
  e.preventDefault();
  const weight = parseFloat(document.getElementById("weightInput").value);
  const notes = document.getElementById("weightNotes").value.trim();

  if (!weight || weight <= 0) {
    alert("Please enter a valid weight in kg.");
    return;
  }

  try {
    await apiRequest("/api/weight", {
      method: "POST",
      body: JSON.stringify({
        log_date: currentTrackingDate,
        weight_kg: weight,
        notes: notes
      })
    });
    document.getElementById("weightInput").value = "";
    document.getElementById("weightNotes").value = "";
    loadWeightTracker();
  } catch (err) {
    alert("Could not log weight: " + err.message);
  }
}

function renderWeightChart(history) {
  const chartSvg = document.getElementById("weightSvgChart");
  if (!chartSvg) return;

  if (history.length < 2) {
    chartSvg.innerHTML = `
      <text x="50%" y="50%" text-anchor="middle" fill="#64748b" font-size="14">
        Log at least 2 weight entries to view progress trend.
      </text>
    `;
    return;
  }

  const padding = 40;
  const width = chartSvg.clientWidth || 500;
  const height = 200;

  const weights = history.map(h => h.weight_kg);
  const minW = Math.min(...weights) - 1.0;
  const maxW = Math.max(...weights) + 1.0;
  const rangeW = maxW - minW || 1;

  const points = history.map((h, i) => {
    const x = padding + (i / (history.length - 1)) * (width - 2 * padding);
    const y = height - padding - ((h.weight_kg - minW) / rangeW) * (height - 2 * padding);
    return { x, y, weight: h.weight_kg, date: h.log_date };
  });

  const polylinePoints = points.map(p => `${p.x},${p.y}`).join(" ");

  let svgContent = `
    <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="rgba(255,255,255,0.1)" stroke-width="1" />
    <polyline fill="none" stroke="#10b981" stroke-width="3" stroke-linecap="round" points="${polylinePoints}" />
  `;

  points.forEach(p => {
    svgContent += `
      <circle cx="${p.x}" cy="${p.y}" r="5" fill="#10b981" stroke="#0a0f1d" stroke-width="2" />
      <text x="${p.x}" y="${p.y - 10}" fill="#f8fafc" font-size="11" text-anchor="middle">${p.weight} kg</text>
      <text x="${p.x}" y="${height - padding + 18}" fill="#64748b" font-size="10" text-anchor="middle">${p.date.slice(5)}</text>
    `;
  });

  chartSvg.innerHTML = svgContent;
}

function renderWeightHistoryTable(history) {
  const tbody = document.getElementById("weightHistoryBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-dim);">No weight records yet.</td></tr>';
    return;
  }

  [...history].reverse().forEach(h => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(h.log_date)}</td>
      <td><strong>${h.weight_kg} kg</strong></td>
      <td>${escapeHtml(h.notes || "-")}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ==========================================================================
// Tab 5: Profile & Targets
// ==========================================================================

async function loadProfileTab() {
  try {
    const data = await apiRequest("/api/profile");
    const p = data.profile || {};
    document.getElementById("profAge").value = p.age || 25;
    document.getElementById("profGender").value = p.gender || "other";
    document.getElementById("profHeight").value = p.height_cm || 170;
    document.getElementById("profWeight").value = p.weight_kg || 70;
    document.getElementById("profActivity").value = p.activity_level || "moderate";
    document.getElementById("profGoal").value = p.goal || "healthy_lifestyle";
    document.getElementById("profDiet").value = p.dietary_preference || "vegetarian";
    document.getElementById("profAllergies").value = p.allergies || "";
    document.getElementById("profCalories").value = p.daily_calorie_target || 2000;
    document.getElementById("profWater").value = p.daily_water_target_ml || 2500;
  } catch (err) {
    console.error("Profile loading error:", err);
  }
}

async function handleProfileSubmit(e) {
  e.preventDefault();
  const btn = e.target.querySelector("button[type='submit']");

  const payload = {
    age: parseInt(document.getElementById("profAge").value),
    gender: document.getElementById("profGender").value,
    height_cm: parseFloat(document.getElementById("profHeight").value),
    weight_kg: parseFloat(document.getElementById("profWeight").value),
    activity_level: document.getElementById("profActivity").value,
    goal: document.getElementById("profGoal").value,
    dietary_preference: document.getElementById("profDiet").value,
    allergies: document.getElementById("profAllergies").value.trim(),
    daily_calorie_target: parseInt(document.getElementById("profCalories").value),
    daily_water_target_ml: parseInt(document.getElementById("profWater").value)
  };

  try {
    btn.disabled = true;
    btn.textContent = "Saving...";
    await apiRequest("/api/profile", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
    alert("Profile and nutritional targets updated successfully!");
  } catch (err) {
    alert("Profile update failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
}

// ==========================================================================
// Hero Preview Chat
// ==========================================================================

async function sendHeroMessage() {
  const input = document.getElementById("heroChatInput");
  const text = input.value.trim();
  if (!text) return;

  const chatBody = document.getElementById("heroChatBody");
  const userMsg = document.createElement("div");
  userMsg.className = "chat-bubble user";
  userMsg.textContent = text;
  chatBody.appendChild(userMsg);
  input.value = "";

  const botMsg = document.createElement("div");
  botMsg.className = "chat-bubble bot";
  botMsg.textContent = "NutriAI is analyzing...";
  chatBody.appendChild(botMsg);
  chatBody.scrollTop = chatBody.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });
    const data = await res.json();
    botMsg.innerHTML = formatDietPlan(data.reply || "I am here to guide your nutrition journey!");
  } catch (err) {
    botMsg.textContent = "Could not connect to NutriAI backend. Please ensure the server is running.";
  }
  chatBody.scrollTop = chatBody.scrollHeight;
}

function quickHeroReply(text) {
  const input = document.getElementById("heroChatInput");
  if (input) {
    input.value = text;
    sendHeroMessage();
  }
}

function toggleMobileMenu() {
  const nav = document.querySelector(".navbar");
  if (nav) nav.classList.toggle("open");
}

// ==========================================================================
// DOM Initialization
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => {
  initAuth().then(() => {
    if (window.location.hash === "#chat" && authToken) {
      switchTab("chat");
    }
  });

  // Auth Forms
  const loginForm = document.getElementById("loginForm");
  if (loginForm) loginForm.addEventListener("submit", handleLoginSubmit);

  const signupForm = document.getElementById("signupForm");
  if (signupForm) signupForm.addEventListener("submit", handleSignupSubmit);

  // Tracker Forms
  const addMealForm = document.getElementById("addMealForm");
  if (addMealForm) addMealForm.addEventListener("submit", handleAddMealSubmit);

  const addWeightForm = document.getElementById("addWeightForm");
  if (addWeightForm) addWeightForm.addEventListener("submit", handleAddWeightSubmit);

  const profileForm = document.getElementById("profileForm");
  if (profileForm) profileForm.addEventListener("submit", handleProfileSubmit);

  // Chat input Enter key
  const chatInput = document.getElementById("chatInput");
  if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") handleSendMessage();
    });
  }

  const heroInput = document.getElementById("heroChatInput");
  if (heroInput) {
    heroInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendHeroMessage();
    });
  }
});
