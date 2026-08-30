class_name BriarKnightRoseBloomController
extends Node2D

signal bloom_visual_peak
signal bloom_finished

@export var bloom_sprite: AnimatedSprite2D

const BLOOM_ANIMATION := &"rose_bloom"
const PEAK_FRAME := 12

var _peak_emitted := false


func _ready() -> void:
	assert(bloom_sprite != null, "Assign the Briar Knight AnimatedSprite2D.")
	bloom_sprite.frame_changed.connect(_on_frame_changed)
	bloom_sprite.animation_finished.connect(_on_animation_finished)


func play_rose_bloom() -> void:
	_peak_emitted = false
	bloom_sprite.position = Vector2.ZERO
	bloom_sprite.play(BLOOM_ANIMATION)


func clear_rosebound_visual() -> void:
	bloom_sprite.play(&"idle")


func _on_frame_changed() -> void:
	if bloom_sprite.animation == BLOOM_ANIMATION and bloom_sprite.frame == PEAK_FRAME and not _peak_emitted:
		_peak_emitted = true
		bloom_visual_peak.emit()


func _on_animation_finished() -> void:
	if bloom_sprite.animation != BLOOM_ANIMATION:
		return
	bloom_sprite.play(&"rosebound_idle")
	bloom_finished.emit()
