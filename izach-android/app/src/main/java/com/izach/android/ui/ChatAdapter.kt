package com.izach.android.ui

import android.view.Gravity
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.R
import com.izach.android.databinding.ItemMessageBinding
import com.izach.android.model.Message

class ChatAdapter : RecyclerView.Adapter<ChatAdapter.VH>() {

    private val items = mutableListOf<Message>()

    fun add(msg: Message) {
        items.add(msg)
        notifyItemInserted(items.size - 1)
    }

    fun setAll(msgs: List<Message>) {
        items.clear()
        items.addAll(msgs)
        notifyDataSetChanged()
    }

    fun isEmpty() = items.isEmpty()

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemMessageBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])
    override fun getItemCount() = items.size

    class VH(private val b: ItemMessageBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(msg: Message) {
            b.tvMessage.text = msg.text
            b.tvTs.text = msg.ts

            val ctx = b.root.context
            when {
                msg.sender == "YOU" -> {
                    b.tvSender.text = "YOU"
                    b.tvSender.setTextColor(ContextCompat.getColor(ctx, R.color.text_sec))
                    b.tvMessage.setBackgroundResource(R.drawable.bg_msg_user)
                    b.tvMessage.setTextColor(ContextCompat.getColor(ctx, R.color.text_pri))
                    b.messageContainer.gravity = Gravity.END
                }
                msg.sender == "system" || msg.sender == "SYSTEM" -> {
                    b.tvSender.text = "SYSTEM"
                    b.tvSender.setTextColor(ContextCompat.getColor(ctx, R.color.amber))
                    b.tvMessage.setBackgroundResource(R.drawable.bg_msg_system)
                    b.tvMessage.setTextColor(ContextCompat.getColor(ctx, R.color.amber))
                    b.messageContainer.gravity = Gravity.CENTER
                }
                else -> {
                    b.tvSender.text = "iZACH"
                    b.tvSender.setTextColor(ContextCompat.getColor(ctx, R.color.cyan))
                    b.tvMessage.setBackgroundResource(R.drawable.bg_msg_izach)
                    b.tvMessage.setTextColor(ContextCompat.getColor(ctx, R.color.text_pri))
                    b.messageContainer.gravity = Gravity.START
                }
            }
        }
    }
}
