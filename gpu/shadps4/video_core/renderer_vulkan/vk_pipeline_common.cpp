// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <atomic>
#include <span>

#include <boost/container/small_vector.hpp>
#include <boost/container/static_vector.hpp>

#include "shader_recompiler/resource.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
#include "video_core/renderer_vulkan/vk_pipeline_common.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {

Pipeline::Pipeline(const Instance& instance_, Scheduler& scheduler_, DescriptorHeap& desc_heap_,
                   const Shader::Profile& profile_, vk::PipelineCache pipeline_cache,
                   bool is_compute_ /*= false*/)
    : instance{instance_}, scheduler{scheduler_}, desc_heap{desc_heap_}, profile{profile_},
      is_compute{is_compute_} {}

Pipeline::~Pipeline() {
    // The descriptor heap caches sets by layout handle. Leaving them there when the layout is
    // destroyed lets a later layout with a recycled handle return a stale set: on NVIDIA that
    // ended in a null read inside the driver after the pipeline cache evicted old pipelines.
    if (!uses_push_descriptors && desc_layout) {
        desc_heap.ForgetLayout(*desc_layout);
    }
}


void Pipeline::BindResources(DescriptorWrites& set_writes,
                             const Shader::PushData& push_data) const {
    // bbport: a default-constructed write (descriptorCount 0, type SAMPLER, pImageInfo null)
    // reached vkCmdPushDescriptorSetKHR and made RADV dereference null (host SIGSEGV on
    // bb:VkRecorder after an area load). Empty writes are dropped; a write whose type needs an
    // info pointer but has none gets a null descriptor instead. Both are reported.
    const auto is_image_type = [](vk::DescriptorType type) {
        return type == vk::DescriptorType::eSampler ||
               type == vk::DescriptorType::eCombinedImageSampler ||
               type == vk::DescriptorType::eSampledImage ||
               type == vk::DescriptorType::eStorageImage ||
               type == vk::DescriptorType::eInputAttachment;
    };
    const auto is_buffer_type = [](vk::DescriptorType type) {
        return type == vk::DescriptorType::eUniformBuffer ||
               type == vk::DescriptorType::eStorageBuffer ||
               type == vk::DescriptorType::eUniformBufferDynamic ||
               type == vk::DescriptorType::eStorageBufferDynamic;
    };
    u32 null_infos = 0;
    u32 first_bad_index = ~0u;
    u32 first_bad_binding = 0;
    u32 first_bad_count = 0;
    u32 first_bad_type = 0;
    static const vk::DescriptorImageInfo null_image{
        VK_NULL_HANDLE, VK_NULL_HANDLE, vk::ImageLayout::eGeneral};
    static const vk::DescriptorBufferInfo null_buffer{VK_NULL_HANDLE, 0, VK_WHOLE_SIZE};
    for (u32 i = 0; i < set_writes.size(); ++i) {
        auto& write = set_writes[i];
        if (write.descriptorCount == 0) {
            continue;
        }
        const bool bad_image = is_image_type(write.descriptorType) && !write.pImageInfo;
        const bool bad_buffer = is_buffer_type(write.descriptorType) && !write.pBufferInfo;
        const bool bad_texel = (write.descriptorType == vk::DescriptorType::eUniformTexelBuffer ||
                                write.descriptorType == vk::DescriptorType::eStorageTexelBuffer) &&
                               !write.pTexelBufferView;
        if (!bad_image && !bad_buffer && !bad_texel) {
            continue;
        }
        if (first_bad_index == ~0u) {
            first_bad_index = i;
            first_bad_binding = write.dstBinding;
            first_bad_count = write.descriptorCount;
            first_bad_type = static_cast<u32>(write.descriptorType);
        }
        if (bad_image) {
            write.pImageInfo = &null_image;
            write.descriptorCount = 1;
        } else if (bad_buffer) {
            write.pBufferInfo = &null_buffer;
            write.descriptorCount = 1;
        } else {
            write.descriptorCount = 0;
        }
        ++null_infos;
    }
    const auto empty_writes = std::erase_if(set_writes, [](const vk::WriteDescriptorSet& write) {
        return write.descriptorCount == 0;
    });
    if (empty_writes != 0 || null_infos != 0) {
        static std::atomic<u32> reported{0};
        if (reported.fetch_add(1, std::memory_order_relaxed) < 16) {
            LOG_WARNING(Render_Vulkan,
                        "Descriptor set for {}: dropped {} empty writes, replaced {} null infos; "
                        "first write {} binding {} type {} count {}",
                        GetDebugString(), empty_writes, null_infos, first_bad_index,
                        first_bad_binding, first_bad_type, first_bad_count);
        }
    }

    const auto bind_point =
        IsCompute() ? vk::PipelineBindPoint::eCompute : vk::PipelineBindPoint::eGraphics;
    const auto stage_flags = IsCompute() ? vk::ShaderStageFlagBits::eCompute : AllGraphicsStageBits;
    const vk::PipelineLayout layout = *pipeline_layout;
    scheduler.Record([layout, stage_flags, push_data](vk::CommandBuffer cmdbuf) {
        cmdbuf.pushConstants(layout, stage_flags, 0u, sizeof(push_data), &push_data);
    });

    // Bind descriptor set.
    if (set_writes.empty()) {
        return;
    }

    if (uses_push_descriptors) {
        if (!scheduler.IsRecordingDeferred()) {
            // RecordNow executes on this thread, so the reference to set_writes stays valid for
            // the whole call. Record() could still defer the closure if another thread changed
            // the recording mode after the check, leaving a dangling vector behind.
            scheduler.RecordNow([&set_writes, bind_point, layout](vk::CommandBuffer cmdbuf) {
                cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, set_writes);
            });
            return;
        }
        // Writes and the infos they point to are laid out in the recording chunk, with the
        // pointers already aimed at those copies: the command only carries a span.
        size_t bytes = set_writes.size() * sizeof(vk::WriteDescriptorSet) + 64;
        for (const auto& write : set_writes) {
            bytes += write.descriptorCount *
                         (sizeof(vk::DescriptorBufferInfo) + sizeof(vk::DescriptorImageInfo) +
                          sizeof(vk::BufferView)) +
                     32;
        }
        scheduler.ReserveRecordData(bytes);
        const auto writes = scheduler.RecordData(std::span<const vk::WriteDescriptorSet>{set_writes});
        auto* patched = const_cast<vk::WriteDescriptorSet*>(writes.data());
        for (size_t i = 0; i < writes.size(); ++i) {
            auto& write = patched[i];
            if (write.pBufferInfo) {
                write.pBufferInfo = scheduler.RecordData(std::span{write.pBufferInfo, write.descriptorCount}).data();
            }
            if (write.pImageInfo) {
                write.pImageInfo = scheduler.RecordData(std::span{write.pImageInfo, write.descriptorCount}).data();
            }
            if (write.pTexelBufferView) {
                write.pTexelBufferView =
                    scheduler.RecordData(std::span{write.pTexelBufferView, write.descriptorCount}).data();
            }
        }
        scheduler.Record([bind_point, layout, writes](vk::CommandBuffer cmdbuf) {
            cmdbuf.pushDescriptorSetKHR(bind_point, layout, 0, writes);
        });
        return;
    }

    // Descriptor set updates are device calls: they stay on this thread.
    const auto desc_set = desc_heap.Commit(*desc_layout);
    for (auto& set_write : set_writes) {
        set_write.dstSet = desc_set;
    }
    instance.GetDevice().updateDescriptorSets(set_writes, {});
    scheduler.Record([bind_point, layout, desc_set](vk::CommandBuffer cmdbuf) {
        cmdbuf.bindDescriptorSets(bind_point, layout, 0, desc_set, {});
    });
}

std::string Pipeline::GetDebugString() const {
    std::string stage_desc;
    for (const auto& stage : stages) {
        if (stage) {
            const auto shader_name = PipelineCache::GetShaderName(stage->hw_stage, stage->pgm_hash);
            if (stage_desc.empty()) {
                stage_desc = shader_name;
            } else {
                stage_desc = fmt::format("{},{}", stage_desc, shader_name);
            }
        }
    }
    return stage_desc;
}

} // namespace Vulkan
