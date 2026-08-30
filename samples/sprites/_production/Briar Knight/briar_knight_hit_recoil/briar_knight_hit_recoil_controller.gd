class_name BriarKnightHitRecoilController
extends Node2D

signal impact_frame
signal recoil_finished

@export var recoil_sprite: AnimatedSprite2D

const RECOIL_ANIMATION := &"hit_recoil"
const IMPACT_FRAME := 1
const RECOIL_OFFSETS := PackedFloat32Array([
	0.0, -2.0, -8.0, -18.0, -28.0, -34.0, -38.0, -40.0,
	-34.0, -26.0, -18.0, -12.0, -7.0, -3.0, -1.0, 0.0,
])

var _impact_emitted := false


func _ready() -> void:
	assert(recoil_sprite != null, "Assign the Briar Knight AnimatedSprite2D.")
	recoil_sprite.frame_changed.connect(_on_frame_changed)
	recoil_sprite.animation_finished.connect(_on_animation_finished)


func play_hit_recoil() -> void:
	_impact_emitted = false
	recoil_sprite.position.x = 0.0
	recoil_sprite.play(RECOIL_ANIMATION)


func _on_frame_changed() -> void:
	if recoil_sprite.animation != RECOIL_ANIMATION:
		return
	var frame_index := clampi(recoil_sprite.frame, 0, RECOIL_OFFSETS.size() - 1)
	recoil_sprite.position.x = RECOIL_OFFSETS[frame_index]
	if frame_index == IMPACT_FRAME and not _impact_emitted:
		_impact_emitted = true
		impact_frame.emit()


func _on_animation_finished() -> void:
	if recoil_sprite.animation != RECOIL_ANIMATION:
		return
	recoil_sprite.position.x = 0.0
	recoil_sprite.play(&"idle")
	recoil_finished.emit()
