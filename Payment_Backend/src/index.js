import "dotenv/config";
import express from "express";
import helmet from "helmet";
import rateLimit from "express-rate-limit";
import Razorpay from "razorpay";
import crypto from "crypto";

const PORT = process.env.PORT || 5000;

const PRICE_INR = 20;
const AMOUNT_PAISE = PRICE_INR * 100;

const { RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET } = process.env;
if (!RAZORPAY_KEY_ID || !RAZORPAY_KEY_SECRET) {
  console.error("Missing RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET");
  process.exit(1);
}

const razorpay = new Razorpay({
  key_id: RAZORPAY_KEY_ID,
  key_secret: RAZORPAY_KEY_SECRET,
});

const app = express();
app.set("trust proxy", 1); 
app.disable("x-powered-by");
app.use(helmet());
app.use(express.json({ limit: "10kb" }));

const limiter = (limit) =>
  rateLimit({
    windowMs: 10 * 60 * 1000,
    limit,
    standardHeaders: true,
    legacyHeaders: false,
    message: { success: false, error: "Too many requests, try again later" },
  });

const RESUME_ID_RE = /^[A-Za-z0-9_-]{8,64}$/;
const ORDER_ID_RE = /^order_[A-Za-z0-9]{6,40}$/;
const PAYMENT_ID_RE = /^pay_[A-Za-z0-9]{6,40}$/;

const isValid = (re, v) => typeof v === "string" && re.test(v);

function safeEqual(a, b) {
  const ba = Buffer.from(a);
  const bb = Buffer.from(b);
  return ba.length === bb.length && crypto.timingSafeEqual(ba, bb);
}


async function isOrderPaidForResume(orderId, resumeId) {
  const order = await razorpay.orders.fetch(orderId);
  return (
    order.status === "paid" &&
    order.currency === "INR" &&
    order.amount === AMOUNT_PAISE &&
    order.amount_paid === AMOUNT_PAISE &&
    order.notes?.resumeId === resumeId
  );
}

app.get("/health", (_req, res) => res.json({ ok: true }));

app.post("/create-order", limiter(30), async (req, res) => {
  try {
    const { resumeId } = req.body ?? {};
    if (!isValid(RESUME_ID_RE, resumeId)) {
      return res.status(400).json({ success: false, error: "Invalid request" });
    }

    const order = await razorpay.orders.create({
      amount: AMOUNT_PAISE,
      currency: "INR",
      receipt: "rcpt_" + crypto.randomUUID().replace(/-/g, "").slice(0, 32),
      notes: { resumeId, product: "resume_pdf" },
    });

    res.json({
      success: true,
      orderId: order.id,
      amount: order.amount,
      currency: order.currency,
      keyId: RAZORPAY_KEY_ID, 
    });
  } catch (err) {
    console.error("create-order failed:", err?.error ?? err);
    res.status(500).json({ success: false, error: "Could not create order" });
  }
});

app.post("/verify-payment", limiter(60), async (req, res) => {
  try {
    const {
      razorpay_order_id: orderId,
      razorpay_payment_id: paymentId,
      razorpay_signature: signature,
      resumeId,
    } = req.body ?? {};

    if (
      !isValid(ORDER_ID_RE, orderId) ||
      !isValid(PAYMENT_ID_RE, paymentId) ||
      !isValid(RESUME_ID_RE, resumeId) ||
      typeof signature !== "string"
    ) {
      return res.status(400).json({ success: false, error: "Invalid request" });
    }

    const expected = crypto
      .createHmac("sha256", RAZORPAY_KEY_SECRET)
      .update(`${orderId}|${paymentId}`)
      .digest("hex");

    if (!safeEqual(expected, signature)) {
      return res.status(400).json({ success: false, error: "Invalid signature" });
    }

    const paid = await isOrderPaidForResume(orderId, resumeId);
    if (!paid) {
      // Signature is valid but order not marked paid yet (capture delay) or belongs to another resume.
      return res.status(202).json({ success: false, paid: false, retry: true });
    }

    res.json({ success: true, paid: true });
  } catch (err) {
    console.error("verify-payment failed:", err?.error ?? err);
    res.status(502).json({ success: false, error: "Could not confirm payment, try again" });
  }
});


app.post("/order-status", limiter(60), async (req, res) => {
  try {
    const { orderId, resumeId } = req.body ?? {};
    if (!isValid(ORDER_ID_RE, orderId) || !isValid(RESUME_ID_RE, resumeId)) {
      return res.status(400).json({ success: false, error: "Invalid request" });
    }
    const paid = await isOrderPaidForResume(orderId, resumeId);
    res.json({ success: true, paid });
  } catch (err) {
    console.error("order-status failed:", err?.error ?? err);
    res.status(502).json({ success: false, error: "Could not check status" });
  }
});


app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(400).json({ success: false, error: "Bad request" });
});

app.listen(PORT, () => {
  console.log(`Server started on port ${PORT}`);
});