import express from "express";
import Razorpay from "razorpay";
import cors from "cors";
import crypto from "crypto";
import dotenv from "dotenv";

dotenv.config();

const app = express();

const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json());

const razorpay = new Razorpay({
    key_id: process.env.RAZORPAY_KEY_ID,
    key_secret: process.env.RAZORPAY_KEY_SECRET,
});

app.post("/create-order", async (req, res) => {
    try {
        const { amount } = req.body;

        if (!amount || isNaN(amount) || amount <= 0) {
            return res.status(400).json({
                success: false,
                error: "Valid 'amount' is required",
            });
        }

        const options = {
            amount: Math.round(amount * 100), // amount in paise
            currency: "INR",
            receipt: "receipt_" + Date.now(),
        };

        const order = await razorpay.orders.create(options);
        res.json({
            success: true,
            order,
        });
    } catch (error) {
        console.error(error);
        res.status(500).json({
            success: false,
            error: error.message,
        });
    }
});

app.post("/verify-payment", async (req, res) => {
    try {
        const { razorpay_order_id, razorpay_payment_id, razorpay_signature } = req.body;

        if (!razorpay_order_id || !razorpay_payment_id || !razorpay_signature) {
            return res.status(400).json({
                success: false,
                message: "Missing required payment verification fields",
            });
        }

        const body = razorpay_order_id + "|" + razorpay_payment_id;

        const expectedSignature = crypto
            .createHmac("sha256", process.env.RAZORPAY_KEY_SECRET)
            .update(body.toString())
            .digest("hex");

        const expectedBuffer = Buffer.from(expectedSignature, "utf-8");
        const receivedBuffer = Buffer.from(razorpay_signature, "utf-8");

        const isValid =
            expectedBuffer.length === receivedBuffer.length &&
            crypto.timingSafeEqual(expectedBuffer, receivedBuffer);

        if (isValid) {
            res.json({
                success: true,
                message: "Payment Verified",
            });
        } else {
            res.status(400).json({
                success: false,
                message: "Invalid signature",
            });
        }
    } catch (error) {
        console.error(error);
        res.status(500).json({
            success: false,
            error: error.message,
        });
    }
});

app.listen(PORT, () => {
    console.log(`Server started at : http://localhost:${PORT}/`);
});